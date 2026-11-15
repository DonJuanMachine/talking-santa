# local/ — your personal files

Everything personal to your family lives in `local/` at the repo root. Git ignores that folder, so nothing in it is
ever committed. This `local.example/` folder is the committed template.

```
local/
  santa.env       your settings and the network PIN      <- copy from local.example/santa.env.example
  santa_world.txt Santa's backstory (optional): replaces the built-in North Pole, Mrs. Claus, reindeer and elves
  santa.jpg       Santa's picture (.jpg, .jpeg, .png or .webp; square, e.g. 800x800)
  profiles.json   your children's names, ages and facts   <- copy from profiles.example.json, or /add in chat.py
  transcripts/    chat.py saves a transcript of each typed session here; /forget in chat.py deletes them
  run/            the log and process id that scripts/start-santa.sh writes
  certs/          santa.pem + santa-key.pem for --network (made with mkcert, see README)
```

Set it up:
```bash
mkdir -p local
cp local.example/santa.env.example local/santa.env    # then edit
cp profiles.example.json local/profiles.json          # then edit
cp ~/Pictures/my-santa.jpg local/santa.jpg            # optional
```

To give Santa your own backstory, write plain sentences in `local/santa_world.txt` (up to 2000 characters). Easiest start: copy `local.example/santa_world.txt.example` to `local/santa_world.txt` (drop the `.example`) and edit it.
Everything in the file is sent to the model as written, so do not add comment lines. Or start from
the built-in one in `santa/persona.py` (`WORLD_DEFAULT`) so Santa keeps the rule to use only these names. For example:
```
SANTA'S WORLD (these facts never change; always answer the same way)
- Your wife is Mrs. Claus, and her first name is Lumi.
- Your elves are Jingle, Pepper and Tinsel; Pepper's favorite helper is a snowman named Biscuit.
- Use only these names. Never invent other names, and never change them.
```

Every file is optional: without it, the app uses its default (the drawn Santa, no children, no PIN).

Restart Santa after editing anything in `local/`: these files are read once, when Santa starts.

To keep the folder outside the repo (for example in iCloud Drive), set `SANTA_LOCAL_DIR=/path/to/folder` in your
shell. The code in git only knows the file names above (`santa/local.py`).
