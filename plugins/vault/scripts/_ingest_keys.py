"""The join key, defined once. No other code computes these (Capture to Week, Ingest run sequence)."""
import hashlib


def body_md5(body):
    """Hex md5 of a thought body as UTF-8, with trailing newlines stripped."""
    return hashlib.md5(body.rstrip('\n').encode('utf-8')).hexdigest()


def thought_ref(source, body):
    return f'{source}+{body_md5(body)}'


def day_md5(path):
    """Hex md5 of a day-file's bytes."""
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()
