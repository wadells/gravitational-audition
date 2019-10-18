from http.client import HTTPConnection, HTTPResponse
from io import BytesIO
import json
import socket
from struct import unpack


"""
The native docker python client found at https://github.com/docker/docker-py/
is probably a fine choice.  However, since we specifically want to:

    1) test the daemon
    2) show my development ability

I've chosen to write a minimal docker client.
"""


class FriendlyHTTPResponse(HTTPResponse):
    # I really like requests .json() method on response objects.
    # this class is solely to enable that -- wdella 2019-10
    def __init__(self, *args, **kwargs):
        super(FriendlyHTTPResponse, self).__init__(*args, **kwargs)

    def json(self):
        """Reads the response body, parses it as json, and returns the result."""
        return json.loads(self.read())


class SocketHTTPConnection(HTTPConnection):
    """
    Wrapper to allow httplib to be used with a file socket.

    HTTPConnection typically expects to be given a http url.
    This is the minimal glue to allow it to be used with a
    file path to a socket instead.
    """
    def __init__(self, base_url, socket_path, timeout=10):
        super(SocketHTTPConnection, self).__init__(
            'localhost', timeout=timeout
        )
        self.socket_path = socket_path
        self.timeout = timeout

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock

    def response_class(self, sock, *args, **kwargs):
        return FriendlyHTTPResponse(sock, *args, **kwargs)


class DockerClient:
    """
    A minimal docker client that can GET & POST to a socket.
    """
    def __init__(self, target):
        self._target = target
        # With more time, I'd do  connection pooling instead of
        # a new connection for each request
        self.conn = SocketHTTPConnection("/", self._target)
        self.conn.connect()

    def get(self, path, headers={}):
        return self.request("GET", path, headers=headers)

    def post(self, path, body=None, headers={}):
        return self.request("POST", path, body=body, headers=headers)

    def request(self, verb, path, body=None, headers={}):
        if type(body) == dict:  # automatic json conversion
            body = json.dumps(body)
        self.conn.request(verb, path, body=body, headers=headers)
        resp = self.conn.getresponse()
        return resp

    # make sure not to  leak connections, close when the client falls out of scope
    def __del__(self):
        self.conn.close()


# The following demux stuff could go in a utils or parsing file, but I decided
# without any other utils functions, that was overkill -- wdella 2019-10
################################################################################

# Size in bytes of a section header in the docker /container/<id>/logs stream
LOG_HEADER_SIZE = 8
LOG_HEADER_FORMAT = '>BxxxL'


def demux_logs(log_stream):
    """
    Docker uses a multiplexed format for returning logs.

    Split a single byte stream into two vanilla strings.

    returns stdout, stderr
    """
    if type(log_stream) == bytes:
        log_stream = BytesIO(log_stream)

    stdout = BytesIO()
    stderr = BytesIO()
    while True:
        header = log_stream.read(LOG_HEADER_SIZE)
        if not header:  # EOF
            break
        stream, content_len = unpack(LOG_HEADER_FORMAT, header)
        if stream == 1:  # stdout
            stdout.write(log_stream.read(content_len))
        elif stream == 2:  # stderr
            stderr.write(log_stream.read(content_len))
        else:
            # TODO better exception class
            raise Exception("Unrecognized stream id while parsing log stream: " + stream)

    stdout = stdout.getvalue().decode("UTF-8")  # TODO: verify this is true
    stderr = stderr.getvalue().decode("UTF-8")
    return stdout, stderr


if __name__ == "__main__":
    target = "/var/run/docker.sock"
    client = DockerClient(target)
    resp = client.get("/images/json")
    data = resp.read()
    print(data)