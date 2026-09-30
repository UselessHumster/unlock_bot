def get_domain_from_txt(txt: str) -> str:
    if "@" not in txt:
        return ""
    return txt.rsplit("@", 1)[1].strip().lower()
