"""Document-level semantics shared by both runners (standard library only)."""
from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import posixpath
import re
from urllib.parse import unquote, urlsplit

WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
IGNORED = {"head", "script", "style", "template"}
BLOCKS = {"p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "td", "section", "article", "body", "hr"}


class DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.hrefs = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in IGNORED:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag in BLOCKS:
            self.text.append(" ")
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in self.hidden:
            index = len(self.hidden) - 1 - self.hidden[::-1].index(tag)
            del self.hidden[index:]
        if not self.hidden and tag in BLOCKS:
            self.text.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def target_name(href, source_path, input_root):
    """Resolve relative links; accept absolute links only inside the input root."""
    root = urlsplit(input_root)
    source = urlsplit(source_path)
    link = urlsplit(href.strip())
    if link.scheme or link.netloc:
        if link.scheme == "gs" and link.netloc == root.netloc:
            path = link.path
        elif link.scheme in {"http", "https"} and link.netloc == "storage.googleapis.com":
            prefix = "/" + root.netloc + "/"
            if not link.path.startswith(prefix):
                return None
            path = "/" + link.path[len(prefix):]
        else:
            return None
    elif not link.path:
        path = source.path
    elif link.path.startswith("/"):
        path = link.path
    else:
        path = posixpath.join(posixpath.dirname(source.path), link.path)
    path = posixpath.normpath(unquote(path))
    root_path = posixpath.normpath(root.path)
    if posixpath.dirname(path) != root_path:
        return None
    return posixpath.basename(path)


def parse_document(path, raw, input_root, valid_names):
    parser = DocumentParser()
    parser.feed(raw.decode("utf-8"))
    parser.close()
    links = Counter()
    ignored_links = 0
    for href in parser.hrefs:
        target = target_name(href, path, input_root)
        if target in valid_names:
            links[target] += 1
        else:
            ignored_links += 1
    words = WORDS.findall("".join(parser.text).casefold().replace("’", "'"))
    trigrams = Counter(" ".join(triplet) for triplet in zip(words, words[1:], words[2:]))
    name = posixpath.basename(urlsplit(path).path)
    audit = {
        "file": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest(),
        "words": len(words), "trigrams": max(0, len(words) - 2),
        "outgoing": sum(links.values()), "ignored_links": ignored_links,
    }
    return {"audit": audit, "links": list(links.items()), "trigrams": list(trigrams.items())}
