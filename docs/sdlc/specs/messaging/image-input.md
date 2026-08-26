# Spec: messaging/image-input

> Owner: BA · Module: messaging · Status: approved · Size: M

## Problem  <!-- Context -->

The bot discards every non-text Feishu message before it reaches the agent, so a user cannot show it
anything. A misaligned button, a failing test run, a design mock, a stack trace on a phone screen — all
of it has to be retyped as prose or abandoned, even though the underlying agent can read images.

## Users & context  <!-- Context -->

- **Primary user**: a developer prompting the bot from a Feishu chat bound to a project · **Secondary**: other members of that chat, who paste images at each other and not at the bot
- **When**: the user pastes or attaches a screenshot, then asks a question about it · **Where**: Feishu group and direct chats, desktop and mobile clients

## Goals  <!-- Context -->

- A user can paste an image and ask about it, and the agent's answer demonstrably reflects the image's content.
- The common client behaviour — image and text arriving as two separate messages — works without the user having to know that is what happened.
- Zero pasted images reach a project's git repository or its working tree.
- A user who pastes an image knows within one interaction whether the bot took it.

## Non-goals  <!-- Context -->

- **Non-image attachments** — `file` (PDF, `.log`, `.csv`), audio, video, and stickers keep today's silent-drop behaviour.
- **Outbound images** — the bot still replies in text and cards only; it does not send images back.
- **OCR or image preprocessing** — the agent interprets the image; the bot only delivers it.
- **Session keying, transport, or the SDK engine** — unchanged (ADR-0003, ADR-0004, ADR-0009).
- **Per-user authorization** — anyone who can already prompt the bot in a chat can attach an image; ADR-0006's per-project policy is unchanged.

## Business rules  <!-- Context -->

- **BR-1 — Sender-scoped hold** A received image is held against the `(sender, chat)` pair. One member's image is never attached to another member's prompt.
- **BR-2 — Hold expiry** A held image expires 10 minutes after the bot receives it.
- **BR-3 — Attachment cap** At most 5 images accompany one prompt. When more are held, the most recent 5 are attached and the older ones are dropped.
- **BR-4 — Size ceiling** An image over 10 MB is rejected outright, never downscaled or truncated.
- **BR-5 — Repo isolation** A received image is never written inside a project's directory, so no project's auto-commit can stage, commit, or push it.
- **BR-6 — Single use** Attaching a held image to a prompt releases the hold; the same image is never attached to a second prompt.
- **BR-7 — Content stays out of logs** Operational logs record that an image was received and its disposition, never its bytes or a copy of it.

## Constraints & non-functional requirements  <!-- Context -->

| Kind | Requirement | Why / source |
|---|---|---|
| Platform | The size ceiling must not sit below Feishu's own image limit, so the bot never rejects an image Feishu was willing to deliver | Elicited; the 10 MB figure is unverified — see *Open questions* |
| Performance | Receiving and holding an image must not block the bot from handling other messages in other chats while it happens | Existing single-process, multi-chat design |
| Performance | The receipt acknowledgement is observable within 5 seconds of the paste under normal network conditions | Elicited: the user needs to know the paste landed before they type |
| Scale | Held and session-retained images must not grow without bound on the host | Elicited; BR-2, BR-3, and AC-13 bound it |
| Other | New user-visible strings are English, matching every existing bot string | No localization framework exists in the project |

## Acceptance criteria  <!-- Contract -->

### AC-1: A pasted image is carried by the next message

> Rules: BR-1, BR-6

- **Given** a user in a chat bound to a project, who has pasted one image and received the receipt acknowledgement
- **When** they send a text message in that chat
- **Then** the agent's turn for that message includes the image, and the reply reflects the image's content
- **And** the acknowledgement for that message reads *"⏳ Processing... (1 image attached)"*

### AC-2: An image and its caption in one message are used together

> Rules: BR-6

- **Given** a user in a chat bound to a project
- **When** they send one rich-text message containing both an image and text
- **Then** the agent's turn for that message includes the image and the text, with no hold and no second message required

### AC-3: Receipt is acknowledged without adding a chat message

- **Given** a user in a chat bound to a project
- **When** they send a message containing only an image
- **Then** the bot adds an emoji reaction to that image message and posts no reply
- **And** no agent turn starts

### AC-4: Plain text is unaffected when nothing is held

- **Given** a user with no held image in a chat bound to a project
- **When** they send a text message
- **Then** the message is processed exactly as it is today, and the acknowledgement reads *"⏳ Processing..."* with no attachment count

### AC-5: An expired image is not attached, and the user is told

> Rules: BR-2

- **Given** a user whose held image was received more than 10 minutes ago
- **When** they send a text message in that chat
- **Then** the agent's turn does not include the image
- **And** the reply reads *"⚠️ Your earlier image expired after 10 minutes and was not included. Paste it again if you still need it."*

### AC-6: Beyond the cap, the newest images win and the drop is visible

> Rules: BR-3

- **Given** a user holding 6 images in a chat bound to a project
- **When** they send a text message
- **Then** the agent's turn includes the 5 most recently received images
- **And** the reply reads *"⚠️ Only the 5 most recent images were attached; 1 older image was dropped."*

### AC-7: An oversized image is rejected on receipt

> Rules: BR-4

- **Given** a user in a chat bound to a project
- **When** they send an image larger than 10 MB
- **Then** nothing is held, no agent turn starts, and the reply reads *"⚠️ That image is over the 10 MB limit and was not attached."*

### AC-8: A failed download is reported, not swallowed

- **Given** a user in a chat bound to a project, and Feishu returning an error for the image's content
- **When** the bot tries to receive the image
- **Then** nothing is held, no agent turn starts, and the reply reads *"⚠️ Could not download that image from Feishu. Try sending it again."*

### AC-9: One member's image never reaches another member's prompt

> Rules: BR-1

- **Given** two users in the same chat, where the first has pasted an image and the second has none held
- **When** the second user sends a text message
- **Then** that agent turn includes no image, and the first user's image remains held for their own next message

### AC-10: A received image never enters the project repository

> Rules: BR-5

- **Given** a project configured with automatic git commit and push, and a user who has pasted an image
- **When** the agent completes a turn that used the image and the automatic commit runs
- **Then** the commit contains no received image, and the project's working tree and git status are unchanged by the image's presence

### AC-11: A held image is used once

> Rules: BR-6

- **Given** a user whose held image was attached to a previous prompt
- **When** they send another text message with nothing newly pasted
- **Then** that agent turn includes no image, and the acknowledgement carries no attachment count

### AC-12: A non-image attachment changes nothing

- **Given** a user in a chat bound to a project
- **When** they send a file, audio, video, or sticker message
- **Then** the bot holds nothing, starts no agent turn, and posts no reply — the behaviour is unchanged from today

### AC-13: Retained images are cleaned up

> Rules: BR-5

- **Given** a session that has used one or more received images
- **When** that session ends, is reset by the user, or is removed by stale-session cleanup
- **Then** every image received for that session is deleted from the host, and no held image survives to attach to a later session's prompt

### AC-14: Every receipt is recorded without its content

> Rules: BR-7

- **Given** operational logging at its default level
- **When** the bot accepts or rejects a received image
- **Then** the log records the disposition, the sender, the chat, and the size
- **And** the log contains neither the image's bytes nor a path to a copy kept solely for logging

## Out of scope (deferred)  <!-- Context -->

- **Non-image attachments** (`file`, audio, video, stickers) — deliberately excluded above; a later increment can extend AC-12's boundary.
- **Cross-session or cross-chat image reuse** — a held image belongs to one `(sender, chat)` pair; sharing it wider collides with `sessions/per-chat-isolation.md`.
- **Localization of the new strings** — no localization framework exists; English matches every existing string.
- **Accessibility of the acknowledgement** — the bot renders no UI of its own; the reaction-only choice carries a caveat, see *Open questions*.
- **Mobile-specific behaviour** — Feishu's mobile client delivers images over the same event path; no separate requirement.
- **Data migration** — nothing about received images is persisted before this feature, so there is no existing data at release.

## Open questions  <!-- Context -->

- **Is 10 MB the right ceiling?** It was chosen to match Feishu's published image limit, but that figure is unverified. Options: (a) keep 10 MB; (b) verify Feishu's current limit and adopt it; (c) drop to 5 MB for a smaller footprint. **Recommendation: (b)** — a cap below the platform's rejects images Feishu would have delivered, which reads as a bug. Owner: user. Target: 2026-09-02.
- **Where may an attachment live for a `restricted` project?** BR-5 keeps images out of the project directory; ADR-0006 confines a restricted project's file-path arguments *to* that directory. The agent can therefore read the image through its own file reads but may be blocked from operating on it via shell commands. Options: (a) accept the limitation and state it; (b) widen the restriction to a per-session attachment directory; (c) place attachments inside the project under an ignored path, contradicting BR-5. **Recommendation: (a) for this feature, and raise (b) as an ADR revision if users hit it** — (c) trades a stated invariant for convenience. Owner: user, with the architect. Target: 2026-09-02.
- **Does a reaction-only acknowledgement work for screen-reader users?** A reaction may not be announced the way a message is. Options: (a) ship reaction-only and revisit on report; (b) reaction plus a text reply in direct chats only. **Recommendation: (a)** — no such user is known on the project today, and (b) is a small change if one appears. Owner: user. Target: on first report.
- **Should AC-14 exist?** Nobody asked for the log line; it comes from the cross-cutting audit-logging category, since the feature writes externally supplied files to the host. **Recommendation: keep it** — it is the only record of what the bot accepted. Owner: user. Target: at approval.

## Changes  <!-- History -->

| CR | What changed |
|---|---|
| — | Initial spec. |
