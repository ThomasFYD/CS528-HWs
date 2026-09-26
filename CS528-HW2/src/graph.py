from html.parser import HTMLParser
from pathlib import PurePosixPath


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attributes = dict(attrs)
        href = attributes.get("href")

        if href and href.lower().endswith(".html"):
            self.links.append(PurePosixPath(href).name)


def parse_links(html_text):
    parser = LinkParser()
    parser.feed(html_text)
    return parser.links


def build_graph(blobs):
    node_names = {
        PurePosixPath(blob.name).name
        for blob in blobs
    }

    outgoing = {node: [] for node in node_names}
    incoming = {node: [] for node in node_names}

    total = len(blobs)

    for index, blob in enumerate(blobs, start=1):
        source = PurePosixPath(blob.name).name
        html_text = blob.download_as_text(encoding="utf-8")
        targets = parse_links(html_text)

        for target in targets:
            # Ignore links whose target is not part of the dataset.
            if target in node_names:
                outgoing[source].append(target)
                incoming[target].append(source)

        if index % 500 == 0 or index == total:
            print(f"Processed {index}/{total} files")

    return outgoing, incoming