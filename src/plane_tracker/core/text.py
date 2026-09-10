import re


def clean_string(string):
    return re.sub(r"[\/\\.,:]", " ", string)
