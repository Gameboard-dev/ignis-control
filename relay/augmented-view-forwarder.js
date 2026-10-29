// Runs inside Ignis's AppContainer (started by ignis/ignis_native.py). Augmented View in a browser tab asks
// Ignis's proxy for http://127.0.0.1:18790; this forwards each request through a named pipe to the launcher's relay
// outside the sandbox, which passes it to the Augmented View server desktop Obsidian runs (127.0.0.1:8790). Named pipes
// are not subject to the AppContainer's network isolation, and this pipe admits only this container, so the sandbox
// reaches that one server and nothing else on the PC. The relay outside decides which requests may pass.
// Arguments: <port> <pipe name>. One request per pipe connection ("Connection: close").

const http = require("http");

const [port, pipe] = process.argv.slice(2);

const server = http.createServer((req, res) => {
  const upstream = http.request(
    {
      socketPath: pipe,
      method: req.method,
      path: req.url,
      headers: { ...req.headers, host: "127.0.0.1", connection: "close" },
      agent: false,
    },
    (up) => {
      res.writeHead(up.statusCode || 502, up.headers);
      up.pipe(res);
    },
  );

  upstream.on("error", (e) => {
    // The relay or the desktop server is not there (desktop Obsidian has not started it)
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "application/json" });
    }
    res.end(JSON.stringify({ error: `Augmented View server not reachable: ${e.code || e.message}` }));
  });

  req.pipe(upstream);
});

server.listen(Number(port), "127.0.0.1", () => {
  console.log(`forwarding http://127.0.0.1:${port} -> ${pipe}`);
});
