def find_duplicates(items):
    dupes = []
    for a in items:
        for b in items:
            if a == b and a not in dupes:
                dupes.append(a)
    return dupes