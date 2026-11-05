"""Sync engine test: two simulated devices + a stand-in for Google Drive.

Usage:  XDG_DATA_HOME=<tmp>/xdg python3 tests/sync_test.py <empty tmp dir> folder
        XDG_DATA_HOME=<tmp>/xdg python3 tests/sync_test.py <empty tmp dir> rclone
"folder" uses sync.FolderRemote; "rclone" runs the real rclone CLI against a local
folder (no Google account needed). Never point it at real data.
"""
import sys, os, time, json
sys.path.insert(0, os.path.expanduser('~/Desktop/Koobs/app')); import store, sync
E=sys.argv[1]; REMOTE=sys.argv[2]   # "folder" or an rclone remote path
ok=lambda c,m: print(('PASS ' if c else 'FAIL ')+m)
files=lambda d: sorted(os.path.relpath(os.path.join(p,f),d) for p,_,fs in os.walk(d) for f in fs)
mk=lambda: sync.FolderRemote(E+'/drive') if REMOTE=='folder' else sync.RcloneRemote(E+'/drive')
drive_books=lambda: sorted(mk().list_books())
for n in ['Moby-Dick (Herman Melville).epub','Cosmos (Carl Sagan).pdf','sub/Walden (Henry David Thoreau).epub',"Don't Panic & Co (A. B. Writer).pdf"]:
    p=os.path.join(E,'A_books',n); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'w').write(n*100)
os.makedirs(E+'/B_books')
A=store.Library(E+'/A_books',E+'/A_data'); A.scan(); A.tag_book('Cosmos (Carl Sagan).pdf','Science'); A.save()
B=store.Library(E+'/B_books',E+'/B_data')
prog=[]
p=sync.run_sync(A, mk(), progress=lambda *a: prog.append(a)); ok(len(p.uploads)==4 and drive_books()==files(E+'/A_books'), f"1. first sync from A uploads all 4 books (progress callbacks: {len(prog)})")
p=sync.run_sync(B, mk()); ok(len(p.downloads)==4 and files(E+'/B_books')==files(E+'/A_books') and 'Science' in B.books['Cosmos (Carl Sagan).pdf']['tags'], "2. new device B downloads everything, tags included")
time.sleep(0.02)
open(E+'/A_books/Dune (Frank Herbert).epub','w').write('dune'); A.scan(); A.tag_book('Dune (Frank Herbert).epub','Sci-Fi'); A.save()
B.trash_books(['sub/Walden (Henry David Thoreau).epub']); B.set_status(['Moby-Dick (Herman Melville).epub'],'reading'); B.save()
sync.run_sync(B, mk()); sync.run_sync(A, mk()); sync.run_sync(B, mk())
ok(files(E+'/A_books')==files(E+'/B_books')==drive_books() and len(drive_books())==4, "3. add on A + remove on B: devices and Drive converge")
ok(A.books['Moby-Dick (Herman Melville).epub'].get('status')=='reading' and 'Sci-Fi' in B.books['Dune (Frank Herbert).epub']['tags'], "   status from B and tag from A crossed over")
p=sync.run_sync(A, mk()); ok(not (p.uploads or p.downloads or p.remote_deletes or p.local_trash), "4. syncing again transfers nothing")
for i in range(12): open(E+f'/A_books/x{i}.pdf','w').write('x')
A.scan(); A.save(); sync.run_sync(A, mk()); sync.run_sync(B, mk())
B.trash_books([k for k in B.books if k.startswith('x')]); B.save()
p=sync.run_sync(B, mk()); ok(len(p.remote_deletes)==12, "5. B pushes its own 12 confirmed removals without asking")
xs=lambda: len([f for f in os.listdir(E+'/A_books') if f.startswith('x')])
try: sync.run_sync(A, mk(), confirm=lambda plan: 'cancel'); ok(False,'guard')
except sync.SyncError as e: ok(xs()==12 and len([k for k in A.books if k.startswith('x')])==12, f"6. Cancel: nothing touched, library rolled back ({e})")
try: sync.run_sync(A, mk(), confirm=lambda plan: 'cancel'); ok(False,'guard')
except sync.SyncError: ok(xs()==12, "   asking again next time (cancel didn't resurrect or lose anything)")
p=sync.run_sync(A, mk(), confirm=lambda plan: 'keep'); ok(xs()==12 and len(p.uploads)==12, "7. Keep them here: A keeps its 12 and re-uploads them")
sync.run_sync(B, mk()); ok(len([f for f in os.listdir(E+'/B_books') if f.startswith('x')])==12, "   …and B gets them back")
B.trash_books([k for k in B.books if k.startswith('x')]); B.save(); sync.run_sync(B, mk())
p=sync.run_sync(A, mk(), confirm=lambda plan: 'trash'); ok(xs()==0 and len(p.local_trash)==12, "8. Move to Trash: A's 12 go to the Trash")
ok(files(E+'/A_books')==files(E+'/B_books')==drive_books(), "   A, B and Drive match")
