# Docker Volumes

## Container vs Volume

- **Container** = the running process (disposable, deleted with `docker rm`)
- **Volume** = the data storage (persists independently on disk)

## Volume Types

### Anonymous Volumes

- Auto-created by Docker when an image defines a VOLUME directive
- Named with random hashes (e.g., `5efc28c032a8e9...`)
- Stored at `/var/lib/docker/volumes/<hash>/_data`
- Survive container removal (`docker rm`) but are easy to lose track of
- Deleted only with `docker volume rm` or `docker volume prune`

### Named Volumes

- Explicitly created (e.g., `docker volume create my-data`)
- Or declared in docker-compose.yml under `volumes:` section
- Stored at `/var/lib/docker/volumes/<name>/_data`
- Easier to manage and reference

### Bind Mounts

- Maps a host directory directly into the container
- Example: `./volumes/influxdb-data:/var/lib/influxdb2`
- Data lives in your project folder — easy to browse, back up, and version
- Best for development — you can see and edit files directly

## What Happens When You Remove a Container?

- `docker rm <container>` — removes the container, volumes are NOT deleted
- `docker compose down` — removes containers and networks, volumes are NOT deleted
- `docker compose down -v` — removes containers, networks, AND named volumes
- Anonymous volumes are never auto-deleted unless you explicitly prune them

## Accessing Volumes

- Named volumes: need `sudo` to browse `/var/lib/docker/volumes/`
- Bind mounts: accessible directly in your project directory (no sudo needed)
