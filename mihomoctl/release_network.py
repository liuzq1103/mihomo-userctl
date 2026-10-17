"""Isolated HTTPS transport worker; no downloaded program is executed."""
import http.client
import os
from pathlib import Path
import sys
import urllib.request

# -I excludes the script directory. Import only our adjacent, installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mihomoctl.release import validate_url


class RedirectGuard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, path, limit):
    validate_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'mihomoctl-release',
                                                   'Accept': 'application/vnd.github+json'})
    opener = urllib.request.build_opener(RedirectGuard())
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError('response status')
        length = response.headers.get('Content-Length')
        if length is not None and (not length.isdecimal() or int(length) > limit):
            raise ValueError('response size')
        used = 0
        with open(path, 'xb') as output:
            os.chmod(path, 0o600)
            while True:
                block = response.read(min(1024 * 1024, limit - used + 1))
                if not block:
                    break
                used += len(block)
                if used > limit:
                    raise ValueError('response limit')
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if length is not None and used != int(length):
            raise ValueError('incomplete response')


if __name__ == '__main__':
    try:
        download(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    except Exception:
        raise SystemExit(2) from None
