# Running the web UI in Docker

`zing serve` is a single-user tool without a login. Outside a container it
only ever listens on loopback (`127.0.0.1`, `::1`, `localhost`) and refuses any
other bind address. A container is the one exception: the server has to listen
on the container's own interfaces for Docker's port publishing to reach it.

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# open http://localhost:8000
```

**Always publish to `127.0.0.1`** (`-p 127.0.0.1:8000:8000`, not `-p 8000:8000`).
A bare `-p 8000:8000` publishes the UI — and every API key typed into it or
stored in a watch — to your network.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ZING_CONTAINER` | unset (`1` in the image) | Allows a non-loopback bind. zing also checks that it really runs in a container (`/.dockerenv`, `/run/.containerenv` or Kubernetes); setting it on a normal host does not open the server up. |
| `ZING_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | Bind address. Anything but loopback needs `ZING_CONTAINER=1`. `--host` wins over it. |
| `ZING_PORT` | `8000` | Port inside the container. `--port` wins over it. |
| `ZING_DATA_DIR` | `~/.zing` (`/data` in the image) | Audit history, monitors (including their API keys) and your own knowledge-base entries. Mount a volume here to keep them. |
| `ZING_SECRET_KEY` | unset | Master key that encrypts the monitors' stored API keys: the key the Monitors page (or `zing secret rotate`) showed you, or `file:/run/secrets/zing_key` / `env:VAR`. Unset, you enter the key on the Monitors page after every container start. Never stored in `ZING_DATA_DIR`. Setting it on a fresh data directory selects encrypted key storage; without it, monitor API keys are not stored at all and must be entered again after every container start. See below. |
| `ZING_KB_DIR` | unset | Extra knowledge-base YAML directory, mounted read-only for example (`-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb`). |
| `ZING_NO_USER_KB` | unset | `1` ignores the knowledge-base entries you added in the UI (`kb.db`). |
| `ZING_ALLOWED_HOSTS` | unset | Comma-separated extra host names the UI answers to, if you reach it under another name than `localhost`/`127.0.0.1`. |

## What protects the UI

- **Host allowlist.** Requests whose `Host` header is not `localhost`,
  `127.0.0.1`, `[::1]` or listed in `ZING_ALLOWED_HOSTS` are refused. This
  stops DNS rebinding, where a website points its own domain at `127.0.0.1` to
  talk to local servers. The port is not checked, so any published host port
  works.
- **Origin and JSON checks.** State-changing requests from another origin are
  refused, and request bodies must be `application/json`, so another website
  cannot submit forms to the local API.
- **Security headers.** The UI cannot be framed by other sites
  (`X-Frame-Options`, `frame-ancestors`), and no referrer leaves the page.
- **Encrypted monitor keys.** Stored API keys are encrypted with a master
  key that is never written to the data volume, so a copy of the volume
  reveals no API key. Without `ZING_SECRET_KEY` the Monitors page shows the key
  once when it is created and asks for it after every container start;
  monitors that need it wait until then. For unattended restarts, hand it in
  as a Docker secret (the server holds it in memory; run one server process
  per data volume):

  ```bash
  # the key the Monitors page showed you, or a new one: zing secret rotate
  docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data \
    -v "$PWD/zing_key:/run/secrets/zing_key:ro" \
    -e ZING_SECRET_KEY=file:/run/secrets/zing_key zing
  ```

  A `ZING_SECRET_KEY` that is not the key the stored API keys use is refused
  (the UI says so). Rotate with `zing secret rotate`; a lost key can only be
  reset on the Monitors page, which drops the stored API keys.
- **Owner-only data.** The data directory is created `0700` and every database
  file is `0600`; the image runs as an unprivileged user.
