# Beehiiv API v2 reference

Endpoint shapes confirmed against `developers.beehiiv.com` and
`beehiiv.com/support` on 2026-08-24 — not guessed. Re-check the real docs
before relying on anything here that isn't already implemented in
`pipeline/beehiiv.py`; Beehiiv can and does change defaults (see the
`status` default-value change below).

Base URL: `https://api.beehiiv.com/v2`. Auth: `Authorization: Bearer
<BEEHIIV_API_KEY>` on every request.

## Pricing tier

Free **Launch** tier includes general API access (publications, posts,
subscribers) but **not** the dedicated Send API. Scale tier ($43/mo+) adds
webhooks, automations, and other write-heavy features. Source: [Plan types
and subscriber plan tier pricing](https://www.beehiiv.com/support/article/23874462928663-plan-types-and-subscriber-plan-tier-pricing).

## GET /publications/{publicationId}

Query params: `expand` (list) — add `stats` for subscriber/engagement
numbers; omitted otherwise.

```json
{
  "data": {
    "id": "string",
    "name": "string",
    "organization_name": "string",
    "referral_program_enabled": "boolean",
    "created": "number (unix timestamp)",
    "stats": {
      "active_subscriptions": "integer",
      "active_premium_subscriptions": "integer",
      "active_free_subscriptions": "integer",
      "average_open_rate": "number",
      "average_click_rate": "number",
      "total_sent": "integer",
      "total_delivered": "integer",
      "total_unique_opened": "integer",
      "total_clicked": "integer"
    }
  }
}
```

(`total_delivered` was seen in a real response 2026-08-24 but isn't
documented on the reference page — treat any field not in the docs as
unconfirmed/best-effort, matching this project's own anti-hallucination
stance on third-party content.)

Source: [Get publication](https://developers.beehiiv.com/api-reference/publications/show).

## GET /publications/{publicationId}/posts

Query params: `limit` (1–100, default 10), `page` (default 1), `status`
(`draft`/`confirmed`/`archived`/`all`), `audience`, `platform`,
`content_tags[]`, `authors[]`, `slugs[]`, `hidden_from_feed`, `expand`
(`stats`, `free_web_content`, `free_email_content`,
`premium_web_content`, `premium_email_content`, `recipients`), `order_by`
(`created`/`publish_date`/`displayed_date`), `direction` (`asc`/`desc`).

```json
{
  "data": [
    {
      "id": "post_...",
      "title": "string",
      "subtitle": "string",
      "status": "draft|confirmed|archived",
      "platform": "web|email|both",
      "audience": "free|premium|both",
      "publish_date": 1666800076,
      "slug": "string",
      "web_url": "string",
      "stats": { "email": {"recipients": 0, "opens": 0, "..."}, "web": {"..."} }
    }
  ],
  "limit": 10, "page": 1, "total_results": 0, "total_pages": 0
}
```

Source: [List posts](https://developers.beehiiv.com/api-reference/posts/index).

## GET /publications/{publicationId}/posts/{postId}

Same fields as list, plus full detail (`content` when `expand`ed).

- **200** — normal response.
- **202** — post is still being created (creation is asynchronous). Retry
  after the `Retry-After` header duration. `pipeline.beehiiv.get_post`
  returns `{"status": "_pending"}` for this case — a sentinel value, never
  a real Beehiiv status.
- **404** with `{"error": "POST_CREATION_FAILED"}` — creation failed and
  will never complete; `pipeline.beehiiv.get_post` raises `BeehiivError`
  for this specific case (distinct from an ordinary 404 for a bad id,
  which just raises via `requests`' own `raise_for_status`).

Source: [Get post](https://developers.beehiiv.com/api-reference/posts/show).

## POST /publications/{publicationId}/posts

Required: `title` (string), plus one of `blocks` (array of structured
content blocks) or `body_content` (raw HTML string — `pipeline/beehiiv.py`
uses this, not `blocks`). Optional: `subtitle`, `post_template_id`, and
others not currently used by this project.

**`status`** controls draft vs. live — this is the field that matters most:

- `"status": "draft"` — stays a draft. **Always pass this explicitly.**
- Before 2026-08-06: omitting `status` published immediately to all free
  subscribers.
- From 2026-08-06 onward: omitting `status` defaults to `draft`.
- `pipeline.beehiiv.create_draft_post` sends `"status": "draft"` on every
  call regardless of the platform default, on purpose — never remove that
  explicit value even though today's default would technically also work.

Response is `201` immediately with just the new post's `id` — creation
continues asynchronously in the background (see the `202`/`404` states
above). `create_draft_post` polls `get_post` up to
`POST_CREATE_POLL_ATTEMPTS` times (`POST_CREATE_POLL_DELAY_SECONDS` apart)
until the post is no longer pending, then raises unless the final `status`
is exactly `"draft"`.

Sources: [Create post](https://developers.beehiiv.com/api-reference/posts/create),
[Using the Send API and Create post endpoint](https://www.beehiiv.com/support/article/36759164012439-using-the-send-api-and-create-post-endpoint).

## Confirmed NOT possible via the API

- **Updating publication settings (name, branding, custom domain) — there
  is no such endpoint.** Confirmed 2026-08-24 against
  `developers.beehiiv.com/api-reference/publications`: the entire
  Publications section is `GET /v2/publications` (list) and
  `GET /v2/publications/{id}` (show) only — no PUT/PATCH/POST/DELETE at
  all. The "Guardrail-radar" vs. "Guardrail Radar" name mismatch found the
  same day can only be fixed by hand in the Beehiiv dashboard
  (Settings → Publication), not via this integration.

## Not yet confirmed / not implemented

- Subscriber list / segment endpoints — not looked up, not implemented.
- The dedicated Send API — deliberately out of scope for this project; see
  `SKILL.md`'s "one rule that matters more than anything else."
