---
name: new-endpoint
description: Add or change an API endpoint the standard way, with its test and its Postman request. Use whenever creating or modifying anything under api/.
---

# New endpoint

Follow every step. An endpoint is not finished until the owner can run it from Postman.

1. **Schema** — define the request and response shapes in `api/schemas/<group>.py`.
2. **Function** — put the logic in `services/`, `trading/`, `exchange/` or `ai/`. The route only validates, calls the function and returns the schema.
3. **Route** — add it to `api/routes/<group>.py` under `/api/v1`, and make sure the group is registered in `api/router.py`.
4. **Protection** — require a valid access token unless it is a health endpoint. If it is dev-only, return 404 when `APP_ENV=production`.
5. **Tests** — in `tests/api/test_<group>.py`: the success case, the no-token case, and one bad input.
6. **Postman** — add the request to `postman/arbipilot.postman_collection.json` in the folder for its group:
   - URL uses `{{base_url}}`; the `Authorization` header uses `Bearer {{access_token}}`.
   - Include an example body, a saved example response and a test that checks the status code.
   - Never save a real token, password or key.
7. **Docs** — add or update its row in `docs/api.md`: method, path, login needed, dev-only or not, what it does.
8. **Prove it** — start the app in development, call the endpoint, and show the owner the request and the response (with any token masked).
9. **Gate** — run `/preflight`.

Then tell the owner: "Re-import the Postman collection to see the new request", and where to find it.
