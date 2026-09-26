from html.parser import HTMLParser
from pathlib import PurePosixPath
from time import perf_counter, sleep

from google.cloud import storage
from google.api_core.exceptions import (
    GatewayTimeout,
    InternalServerError,
    ServiceUnavailable,
    TooManyRequests,
)
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError,
    Timeout,
)


RETRYABLE_ERRORS = (
    ConnectionError,
    Timeout,
    ChunkedEncodingError,
    GatewayTimeout,
    InternalServerError,
    ServiceUnavailable,
    TooManyRequests,
)


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


def download_html(blob):
    for attempt in range(1, 4):
        client = storage.Client.create_anonymous_client()

        try:
            fresh_blob = client.bucket(blob.bucket.name).blob(
                blob.name,
                generation=blob.generation,
            )

            return fresh_blob.download_as_text(
                encoding="utf-8",
                timeout=(10, 30),
                retry=None,
            )

        except RETRYABLE_ERRORS as error:
            print(
                f"Download failed: {blob.name}, "
                f"attempt {attempt}/3, "
                f"{type(error).__name__}: {error}",
                flush=True,
            )

            if attempt == 3:
                raise RuntimeError(
                    f"Could not download {blob.name} "
                    "after 3 attempts"
                ) from error

        finally:
            client.close()

        sleep(2 * attempt)


def build_graph(blobs):
    node_names = {
        PurePosixPath(blob.name).name
        for blob in blobs
    }

    outgoing = {node: [] for node in node_names}
    incoming = {node: [] for node in node_names}

    total = len(blobs)
    start = perf_counter()

    for index, blob in enumerate(blobs, start=1):
        source = PurePosixPath(blob.name).name

        if index == 1 or (index - 1) % 10 == 0:
            print(
                f"Downloading {index}/{total}: {blob.name}",
                flush=True,
            )

        html_text = download_html(blob)
        targets = parse_links(html_text)

        for target in targets:
            if target in node_names:
                outgoing[source].append(target)
                incoming[target].append(source)

        if index % 10 == 0 or index == total:
            elapsed = perf_counter() - start
            print(
                f"Processed {index}/{total} files "
                f"({100 * index / total:.1f}%), "
                f"elapsed: {elapsed:.1f}s",
                flush=True,
            )

    return outgoing, incoming