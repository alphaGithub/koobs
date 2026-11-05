"""One-off initial tagging.

1. Import tags from the old category folders (shortcuts into All/).
2. Apply the hand-written MANUAL mapping below to books the folders missed.
3. Print a report.

Safe to re-run: it only adds tags, never removes them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from store import (DEFAULT_BOOKS_DIR, DEFAULT_DATA_DIR, ROOT, Library,  # noqa: E402
                   load_config, parse_name)

FOLDERS = ["Biography", "CS", "Communication", "Engineering", "Finance", "History",
           "Math", "Novel", "Others", "Physics", "Psychology", "cs"]
FOLDER_ALIAS = {"cs": "CS"}

# Path prefix (relative to All) -> tags. First matching prefix wins.
MANUAL = {
    # CS / programming
    "Design Patterns": ["CS", "Programming"],
    "Head First Design Patterns": ["CS", "Programming"],
    "System Design Interview": ["CS", "System Design"],
    "Operating Systems Design and Implementation": ["CS"],
    "Agentic AI for Engineers": ["CS", "AI"],
    "Learning Go": ["CS", "Programming"],
    "The Go Programming Language": ["CS", "Programming"],
    "Are You Smart Enough to Work at Google": ["CS", "Others"],
    "Digital Computer Electronics": ["CS", "Engineering"],
    "cs/Prentice Hall - Computer Networks": ["CS", "Networks"],
    "cs/Data Communications and Networking": ["CS", "Networks"],
    "cs/Computer_Networks_Peterson": ["CS", "Networks"],
    "cs/The C Programming Language": ["CS", "Programming"],
    "cs/Operating_System": ["CS", "Operating Systems"],
    "cs/Galvin": ["CS", "Operating Systems"],
    "cs/Modern Operating System": ["CS", "Operating Systems"],
    "cs/Ramakrishnan": ["CS", "Databases"],
    "cs/Database": ["CS", "Databases"],
    "cs/discrete-mathematics": ["CS", "Math"],
    "cs/Kenneth Rosen": ["CS", "Math"],
    "cs/McGraw.Hill.Discrete": ["CS", "Math"],
    "cs/Discrete_and_Combinatorial": ["CS", "Math"],
    "cs/Introduction-to-Automata": ["CS"],
    "cs/computer organisation": ["CS", "Engineering"],
    "cs/digital": ["CS", "Engineering"],
    "cs/Introduction_to_algorithms": ["CS", "Algorithms"],
    # Notes (GATE prep etc.)
    "notes/Ai/": ["Notes", "CS", "AI"],
    "notes/Maths": ["Notes", "Math"],
    "notes/physics": ["Notes", "Physics"],
    "notes/Physics": ["Notes", "Physics"],
    "notes/Aptitude": ["Notes"],
    "notes/": ["Notes", "CS"],
    # Physics / science
    "Three Roads to Quantum Gravity": ["Physics"],
    "Six Not-So-Easy Pieces": ["Physics"],
    "Six Easy Pieces": ["Physics"],
    "The Feynman Lectures": ["Physics"],
    "Geons, Black Holes": ["Physics", "Biography"],
    "Cosmos": ["Physics", "Science"],
    "What is Life": ["Science", "Physics"],
    "The Selfish Gene": ["Science"],
    # Math
    "Euclids Elements": ["Math"],
    "Introduction to Stochastic Processes": ["Math"],
    "Linear Algebra and Its Applications": ["Math"],
    # Finance / trading
    "One Good Trade": ["Finance", "Trading"],
    "Forex Trading": ["Finance", "Trading"],
    "Market Wizards": ["Finance", "Trading"],
    # Fiction
    "The Three-Body Problem": ["Novel", "Sci-Fi"],
    "Three-Body Problem": ["Novel", "Sci-Fi"],
    "The Dark Forest": ["Novel", "Sci-Fi"],
    "The MANIAC": ["Novel"],
    "The Count of Monte Cristo": ["Novel"],
    "The Lord of the Rings": ["Novel", "Fantasy"],
    # Philosophy / spirituality / self-help
    "Complete Works of Friedrich Nietzsche": ["Philosophy"],
    "Five Dialogues": ["Philosophy"],
    "Srimad Bhagavad Gita": ["Philosophy", "Spirituality"],
    "The Game of Life and How to Play It": ["Spirituality", "Psychology"],
    "The War of Art": ["Psychology"],
    "Ultralearning": ["Psychology"],
    "Cues Master the Secret Language": ["Communication"],
}


def link_target(path):
    t = os.readlink(path)
    if "/Books/All/" in t:
        return t.split("/Books/All/", 1)[1]
    if "/Koobs/All/" in t:
        return t.split("/Koobs/All/", 1)[1]
    return os.path.relpath(os.path.normpath(os.path.join(os.path.dirname(path), t)),
                           os.path.join(ROOT, "All"))


def main():
    cfg = load_config() or {"books_dir": DEFAULT_BOOKS_DIR, "data_dir": DEFAULT_DATA_DIR}
    lib = Library(cfg["books_dir"], cfg["data_dir"])
    lib.scan()
    if "--refresh-names" in sys.argv:  # re-parse titles/authors from filenames
        for rel, b in lib.books.items():
            b["title"], b["author"] = parse_name(rel)

    imported, unmatched = 0, []
    for folder in FOLDERS:
        d = os.path.join(ROOT, folder)
        if not os.path.isdir(d):
            continue
        tag = FOLDER_ALIAS.get(folder, folder)
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if not os.path.islink(p):
                continue
            rel = link_target(p)
            if rel in lib.books:
                lib.tag_book(rel, tag)
                imported += 1
            else:
                unmatched.append(f"{folder}/{name} -> {rel}")

    manual = 0
    for rel, b in lib.books.items():
        for prefix, tags in MANUAL.items():
            if rel.startswith(prefix):
                for t in tags:
                    lib.tag_book(rel, t)
                manual += 1
                break

    lib.save()

    print(f"folder links imported: {imported}, unmatched: {len(unmatched)}")
    for u in unmatched:
        print("  UNMATCHED", u)
    print(f"manual rules applied to {manual} books")
    print(f"\n{len(lib.books)} books, {len(lib.tags)} tags")
    for t, n in sorted(lib.counts().items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {t}")
    untagged = [r for r, b in lib.books.items() if not b["tags"]]
    print(f"\nuntagged: {len(untagged)}")
    for r in untagged:
        print("  ", r)


if __name__ == "__main__":
    main()
