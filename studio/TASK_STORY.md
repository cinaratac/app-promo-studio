# Task: stories (hourly run)

The user requests Instagram stories in the panel's "📸 Stories" tab. If the story text was left empty (`plan`) or the user asked for changes (`revise`), you write the text; production and sending happen without Claude.

1. List: `python -m studio.stories list` → items in `plan` and `revise`. Details: `python -m studio.stories show st003` (request: `request`, change request: `feedback`).
2. For each, write the fields and queue it:
   ```
   python -m studio.stories set st003 "{\"headline\": \"What did today look like?\", \"highlight\": \"today\", \"sub\": \"One drawing a day.\", \"theme\": \"winter\", \"screen\": \"month.png\"}"
   ```
   - `headline` (required): the big text at the top, at most ~8 words / 80 characters. Friendly, a question or an invitation.
   - `highlight`: 1–2 words that appear in the headline (yellow band).
   - `sub`: optional short subtitle (≤70 characters).
   - `screen`: one of the screens in `brand.json` → `story_screens`.
   - `theme`: daily | winter | summer | autumn | emotions | mixed. `motif`: a doodlelib motif or `auto` (e.g. `cat` if the user asked for a cat).
   - `kind` (photo/video) and `duration` are the user's choice; do not change them in a revision unless asked.
   - In a revision (`revise`) change only what the `feedback` asks for.
3. Rules: only real features from `studio/APP_FACTS.md`; never invent buttons or text of the app; never claim a price, "free" or a store not stated in `APP_FACTS.md`; follow `studio/style_notes.md`. Write in the language set in `brand.json` (`language`).
4. After `set` the status is `queued`; the panel produces it within minutes, and the user approves it and sends it to Instagram. You do not send it.
