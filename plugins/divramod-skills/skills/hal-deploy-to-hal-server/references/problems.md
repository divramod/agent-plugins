# Problems met, each a check

One line per check (`learn <slug>` appends it): `slug`: the problem (the check, its test). `test_checks.py` fails on a
check missing here or without its test.

- `dockerfile-missing`: the repository has no Dockerfile, so there is no image to deploy (checks/dockerfile_missing.py, test_check_dockerfile_missing.py)
- `port-mismatch`: the declared port is not one the Dockerfile exposes (checks/port_mismatch.py, test_check_port_mismatch.py)
- `undeclared-env`: a name in `.env.example` is neither an env value nor a secret of the declaration (checks/undeclared_env.py, test_check_undeclared_env.py)
- `next-standalone`: a Next.js app without output: standalone ships all of node_modules, which the image size cap and the read-only root do not forgive (checks/next_standalone.py, test_check_next_standalone.py)
- `health-route`: the declared health path is not found in the repository, or its handler answers 503 without the database or 429 under the engine's polling, so a healthy image is kept out (checks/health_route.py, test_check_health_route.py)
- `one-app-one-site`: the repository holds several deployable apps and a site is one container: each app needs its own site (checks/one_app_one_site.py, test_check_one_app_one_site.py)
- `neon-driver`: the Neon serverless driver speaks Neon's HTTP proxy and cannot talk to a plain Postgres (checks/neon_driver.py, test_check_neon_driver.py)
- `vercel-runtime`: the build is made for Vercel (preset or adapter, VERCEL_ENV read at runtime), which behaves differently in a plain container (checks/vercel_runtime.py, test_check_vercel_runtime.py)
- `object-storage`: the app needs object storage, which the server does not offer (plan 0759 Q1), and a container's only writable paths are tmpfs (checks/object_storage.py, test_check_object_storage.py)
- `postgres-needed`: the app needs Postgres, which the server does not offer (plan 0759 Q1): the database stays hosted and the site needs egress (checks/postgres_needed.py, test_check_postgres_needed.py)
- `floating-tag`: the repository's compose or CI runs a floating image tag such as :latest, while the server deploys one digest (checks/floating_tag.py, test_check_floating_tag.py)
- `image-name-mismatch`: the declared image is not the repository the farm's compose or CI publishes, so a digest of it will not pull (checks/image_name_mismatch.py, test_check_image_name_mismatch.py)
- `apex-host`: the app lives on the zone's apex, which hal9k refuses (plan 0759 D14) (checks/apex_host.py, test_check_apex_host.py)
- `build-time-env`: NEXT_PUBLIC_, VITE_ and PUBLIC_ names are inlined at build time, so the container's env never reaches them (checks/build_time_env.py, test_check_build_time_env.py)
- `readonly-root`: the container's root is read-only and only declared paths are writable tmpfs, but the app writes to /tmp or Next.js's cache (checks/readonly_root.py, test_check_readonly_root.py)
- `dockerfile-root-user`: the image has no USER in its final stage, so the app runs as root inside the container (checks/dockerfile_root_user.py, test_check_dockerfile_root_user.py)
- `image-size`: the final stage carries a full node_modules, so the image may pass max_image and the pull is refused (checks/image_size.py, test_check_image_size.py)
- `build-context`: the farm's CI builds with a context in which the Dockerfile's COPY sources do not exist, so no image can be built (checks/build_context.py, test_check_build_context.py)
- `host-clash`: a host of this declaration is already served by another declared site: apply quarantines the clashing route and retries it on its 5-minute timer, so a cut-over moves the host in one commit (checks/host_clash.py, test_check_host_clash.py)
- `deploy-content`: the farm's deploy compose file (utils/docker-compose/deploy/remote-hub/docker-compose.yml, its one description, steueragenten plan 0760) and the [container] table disagree on image, port, env names or memory (checks/deploy_content.py, test_check_deploy_content.py)
