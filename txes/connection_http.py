import codecs
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO
import urllib

import anyjson

from twisted.internet import defer, reactor, protocol
from twisted.web import client
from twisted.web import iweb
from twisted.web import http
from zope import interface

from txes import exceptions, interfaces, utils


DEFAULT_SERVER = "127.0.0.1:9200"


class StringProducer(object):
    interface.implements(iweb.IBodyProducer)

    def __init__(self, body):
        self.body = body
        self.length = len(self.body)

    def startProducing(self, consumer):
        return defer.maybeDeferred(consumer.write, self.body)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass


class JSONProducer(StringProducer):
    def __init__(self, body):
        StringProducer.__init__(self, anyjson.serialize(body))


class JSONReceiver(protocol.Protocol):
    def __init__(self, deferred):
        self.deferred = deferred
        self.writter = codecs.getwriter("utf_8")(StringIO.StringIO())

    def dataReceived(self, bytes):
        # Unicode handling in python is a big mess
        if isinstance(bytes, str):
            self.writter.write(unicode(bytes, "utf-8"))
        else:
        self.writter.write(bytes)

    def connectionLost(self, reason):
        if reason.check(client.ResponseDone, http.PotentialDataLoss):
            try:
                data = anyjson.deserialize(self.writter.getvalue())
            except ValueError:
                data = {"error": reason}
            self.deferred.callback(data)
        else:
            self.deferred.errback(reason)


class HTTPConnection(object):
    interface.implements(interfaces.IConnection)

    def addServer(self, server):
        if server not in self.servers:
            self.servers.append(server)

    def getAgent(self):
        try:
            return self.client
        except AttributeError:
            self.client = client.Agent(reactor)
            return self.client

    def connect(self, servers=None, timeout=None, retryTime=10,
                *args, **kwargs):
        if not servers:
            servers = [DEFAULT_SERVER]
        elif isinstance(servers, (str, unicode)):
            servers = [servers]
        self.servers = utils.ServerList(servers, retryTime=retryTime)
        self.agents = {}

    def close(self):
        pass

    def execute(self, method, path, body=None, params=None):
        def raiseExceptions(body, response):
            status = int(response.code)
            if status != 200:
                exceptions.raiseExceptions(status, body)
            return body

        def parseResponse(response):
            d = defer.Deferred()
            response.deliverBody(JSONReceiver(d))
            return d.addCallback(raiseExceptions, response)

        agent = self.getAgent()
        server = self.servers.get()
        if not path.startswith('/'):
            path = '/' + path
        url = server + path

        if params:
            url = url + '?' + urllib.urlencode(params)

        if isinstance(body, basestring):
            body = StringProducer(body)
        else:
            body = JSONProducer(body)

        if not url.startswith("http://"):
            url = "http://" + url

        d = agent.request(method, str(url), bodyProducer=body)
        d.addCallback(parseResponse)
        return d
