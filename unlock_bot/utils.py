def get_domain_from_txt(txt):
    given_domain = txt.split('@')
    given_domain.reverse()
    return given_domain[0]