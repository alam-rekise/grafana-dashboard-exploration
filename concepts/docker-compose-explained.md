# Docker Compose Explained

## What Is Docker Compose?

Docker Compose lets you define and run multi-container applications with a single YAML file.
Instead of running multiple `docker run` commands with flags, you declare everything in `docker-compose.yml`.

## Our docker-compose.yml Breakdown

```yaml
services:
  influxdb:
    image: influxdb:2.7              # Docker image to use
    container_name: influxdb         # Fixed name (so other containers can reach it)
    ports:
      - "8086:8086"                  # host:container — exposes InfluxDB UI/API
    volumes:
      - ./volumes/influxdb-data:/var/lib/influxdb2    # database files
      - ./volumes/influxdb-config:/etc/influxdb2      # config files
    networks:
      - influx-net                   # shared network with Grafana

  grafana:
    image: grafana/grafana:10.1.2
    container_name: grafana
    ports:
      - "3000:3000"                  # Grafana web UI
    volumes:
      - ./volumes/grafana-data:/var/lib/grafana                              # Grafana state
      - ./provisioning/datasources:/etc/grafana/provisioning/datasources     # auto-configure datasources
      - ./provisioning/dashboards:/etc/grafana/provisioning/dashboards       # auto-load dashboards
    networks:
      - influx-net

networks:
  influx-net:
    driver: bridge                   # default Docker network type
```

## Key Concepts

### Services

Each `service` becomes a running container. We have two: `influxdb` and `grafana`.

### Ports

`"8086:8086"` maps host port 8086 to container port 8086.
Format: `host_port:container_port`

This is what lets you open http://localhost:8086 in your browser.

### Volumes (Bind Mounts)

```yaml
- ./volumes/influxdb-data:/var/lib/influxdb2
#  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#  host path              : container path
```

This maps a directory on your machine to a directory inside the container.
When the container writes to `/var/lib/influxdb2`, the files appear in `./volumes/influxdb-data/` on your host.

### Networks

```yaml
networks:
  influx-net:
    driver: bridge
```

Both containers are on the same `influx-net` network. This means:
- Grafana can reach InfluxDB at `http://influxdb:8086` (using the container name as hostname)
- From your host machine, you use `http://localhost:8086`
- Container-to-container communication uses container names, not `localhost`

This is why the datasource URL in Grafana provisioning is `http://influxdb:8086` (not `localhost`).

## Common Commands

| Command                         | What it does                                           |
| ------------------------------- | ------------------------------------------------------ |
| `docker compose up`             | Start all services (logs in foreground)                 |
| `docker compose up -d`          | Start all services (detached/background)                |
| `docker compose down`           | Stop and remove containers + networks (data safe)       |
| `docker compose down -v`        | Stop + remove containers + networks + named volumes     |
| `docker compose restart grafana`| Restart just Grafana (picks up provisioning changes)    |
| `docker compose ps`             | Show running containers                                 |
| `docker compose logs grafana`   | View Grafana logs                                       |
| `docker compose logs -f`        | Follow logs from all services (live)                    |

## Why Not Just Use `docker run`?

With `docker run`, you'd need:

```bash
docker network create influx-net
docker run -d --name influxdb --network influx-net -p 8086:8086 -v ./volumes/influxdb-data:/var/lib/influxdb2 influxdb:2.7
docker run -d --name grafana --network influx-net -p 3000:3000 -v ./volumes/grafana-data:/var/lib/grafana grafana/grafana:10.1.2
```

With Docker Compose, it's one file and one command: `docker compose up`. Easier to read,
version control, and share with teammates.
