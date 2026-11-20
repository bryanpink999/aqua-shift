# Maple guild shift bot

Each map has its own daily timetable, main roster, sub list and Discord role. Players see handoff times in their local timezone. The bot uses the timezone the admin selects when interpreting the daily timetable. Dates and overnight shifts are automatic.

## First install in your personal server

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications). On **Bot**, enable **Server Members Intent** so the bot can match active players to map roles. Copy the bot token privately.
2. Under **Installation**, enable **Guild Install** with the scopes **bot** and **applications.commands**. Use the install link to add it to your personal server. This bot receives interactions through the gateway. Leave the Interactions Endpoint URL blank.
3. Create the roles **DSG** and **FH** and a text channel such as **#shift-test**. Give yourself the roles you want to test. Give the bot **View Channel**, **Send Messages**, and **Read Message History** there. For role pings, either make the two roles mentionable or allow the bot **Mention @everyone, @here, and All Roles** in that channel. The bot restricts outgoing role mentions to the configured map role. Guild members need channel access and **Use Application Commands**.
4. Enable Discord Developer Mode, right-click the server icon and choose **Copy Server ID**. Install Python 3.11 or newer and extract the ZIP. Open a terminal in the extracted folder containing bot.py.

**On a Mac**, run the following. The token prompt hides what you paste.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v
export GUILD_ID='paste-your-personal-server-id'
export DISCORD_TOKEN="$(python -c 'import getpass; print(getpass.getpass("Bot token: "))')"
python bot.py
```

**On Windows**, run this in PowerShell.

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m unittest -v
$env:GUILD_ID = 'paste-your-personal-server-id'
$env:DISCORD_TOKEN = .\.venv\Scripts\python -c 'import getpass; print(getpass.getpass())'
.\.venv\Scripts\python bot.py
```

While the bot runs, open Discord and type **/map_setup**. The bot registers commands in the server identified by GUILD_ID. Keep the token private. If it is exposed, reset it in the Developer Portal. Discord’s [installation guide](https://docs.discord.com/developers/quick-start/getting-started) explains the application and test-server settings.

## Set up the first rotation

Run **/map_setup** once for DSG and once for FH. For each, select its role, announcements channel and timezone. For Singapore use **Asia/Singapore**. Maps can share a channel or have separate channels. To add another map later, repeat the command. Running it again with the same name updates the map configuration.

Open **/manage**, pick your own timezone, then select **DSG → Add shift**. Enter both times in your local 24-hour clock. Each admin has a saved preference. Change it with **Change my timezone**, or use the **timezone** option on **/manage** to search for any supported city. Your draft displays local times and the save confirmation shows both zones. Conversion uses the offsets in effect when you open the form. The published daily shift stays anchored to the map timezone if seasonal offsets later change. For example, create **23:00–03:00**, **03:00–11:00**, **11:00–17:30** and **17:30–23:00**, each with four seats. Equal start and end times mean one full day. FH can have a completely different timetable and seat count.

Select a draft shift and use **Assign main** or **Assign sub**. Pick the Discord member and enter their usual platform or comment, such as “left side, 3F/4F.” Members can use **/sign_up → map → time → Join as main / Join as sub** after publication. For a single occurrence, choose **Join this shift only** after selecting the map. Self-signup requires no map role or moderator permission. Assign recurring members before first publication if you want them included in the very first shift.

Press **Publish timetable**. In the test server you can publish a single shift and leave hours unscheduled. Overlapping shifts are blocked. Other servers still require full-day coverage. A timetable can be published with empty seats. A party of three can start a four-seat DSG shift with one vacancy. Admin controls require the Discord **Manage Server** permission.

## What members do

| Action | Where to go | What happens |
|---|---|---|
| Take a daily slot | /sign_up → map → time → Join as main or Join as sub | Registers you for that recurring shift. Add a preferred platform or a comment. |
| Join today only | Shift announcement → View / join roster | Take a vacant full seat, join the sub list or browse open handoffs. |
| Confirm attendance | Personal mention in the map channel → I’m showing up | Each main gets an individual check-in about 30 minutes before the shift. Only the named player can answer. |
| Decline | Check-in → I can’t make it | Opens that seat for this occurrence and keeps your recurring signup. Include the platform that needs filling. |
| Look for training | /lf | Enter hours available from now and an optional platform/comment. Your DSG and FH roles select eligible maps automatically. With both roles you can receive calls for either map. |
| See available players | Shift announcement → Looking for a seat | Shows the active /lf pool for that map, each player’s end time and comment. |
| Leave early | /replace or roster → Request replacement | Opens the remainder of your current booking. Enter the platform you need filled. |
| Take a break | /cover or roster → Request cover | Enter duration in hours and the requested platform. The bot reserves your return time and pings you when cover ends. |
| Fill a gap | Opening → Claim all or part | Enter the hours you can take from handoff, or leave hours blank for the available interval. Confirm your platform/comment. |
| Escalate urgently | Open request → Ping map role | Any member who can see the request can press it immediately. One role ping per open gap. |

**Platform** means your position in the Maple map, such as “top left” or “3F/4F.” It is a note other players can read. The bot matches by timing, map roles and bookings. It leaves platform suitability to the players.

## How pings and partial handoffs work

A pre-shift decline calls the registered subs first. If the gap is still open after five minutes, eligible /lf players are pinged. If no eligible registered sub is found when posting, /lf players are included immediately. For /replace and /cover, eligible subs get first call. After five minutes the bot calls matching /lf players if the request is still open. With no eligible subs it checks /lf immediately. Recurring subs on the same map with overlapping signup hours can be pinged even without an active shift. In the test server all published sub signup times on the selected map qualify. Partial handoffs call both groups immediately. **Ping map role** is always available immediately on an open request until someone uses it. Silence on a check-in leaves the seat marked **pending** for the shift lead.

A player uses **/lf** at midnight for 1.5 hours and writes “bottom lane.” At 00:10 they see a DSG replacement through 03:00. A full claim gives them **00:10–01:30**. The roster records their name and platform, and the bot opens **01:30–03:00** for the next person with the original platform request. The next player can book it immediately. A sub or map-role member can also type a shorter duration while claiming. Overlapping claims across DSG and FH are rejected, and two simultaneous clicks cannot win the same opening.

For temporary cover the final handoff is the original trainer’s return. A returned seat stays reserved even if the trainer is late. The trainer can use **I can’t make it** on the return reminder to advertise the remaining interval. When requesting a replacement or break, wait for the claim announcement before leaving the map. The bot cannot observe who is in the game.

**Edit availability** restarts the /lf duration from the edit time. **Stop looking** withdraws future /lf availability. Time already claimed stays booked. Availability expires automatically. The platform/comment is optional in all player signup, availability, handoff and claim forms.

## Editing the daily timetable

Choose the map in **/manage**, select a shift, then **Edit timing / seats**. You can add shifts or remove them from the draft. Publish after adjusting adjoining intervals. If a four-seat shift already has four recurring mains, remove or reassign someone before publishing it with three seats.

A shift gets its own roster when its 30-minute check-in window opens. That roster and its times stay fixed for the occurrence. Recurring edits apply to occurrences that open afterward. At a timetable changeover the first new interval can be shortened so it starts precisely when the already-open rotation finishes. A person already booked on another map cannot be silently double-booked. The second shift advertises their seat as a vacancy. For schedule changes, tell affected regulars in the map channel. Each gets their normal check-in when the new occurrence opens.

## Test it solo

**Offline:** Run `python -m unittest -v` from the project directory. The tests use simulated guild members, a controllable clock and disposable databases. They cover member matching, actual Discord modal and button handlers, 30-minute reminders, overnight scheduling, partial handoffs, simultaneous claims, return times and restart persistence. No token is needed for this run.

**In your personal server:** Choose a boundary five minutes from now in the map’s timezone. If it is 20:10, create two shifts **20:15–08:00** and **08:00–20:15**. Assign yourself as main on the 20:15 draft before publishing. Since that shift is already in its reminder window, the check-in arrives on the next scheduler pass (normally around ten seconds). Press **I can’t make it**, enter “bottom left”, then press **Ping map role**. Check the channel for exactly one role mention and the requested platform. Give yourself both roles and try **/lf** for 0.5 hours. Use the private confirmation to edit or stop looking.

For a live cover rehearsal, join a vacant main seat in the **current** shift, use **/cover** for **0.05 hours** (three minutes), then verify your return reminder. The requester cannot claim their own gap. Use the offline tests to play both sides yourself, or ask one guildmate with the map role to tap **Claim all or part** and check real notification delivery from a second account.

## Running it for the guild

Run one bot process on an always-on machine with a persistent disk. Closing the process or sleeping a laptop pauses reminders. The bot stores rosters, availability, claims and pending sends in **rotation.sqlite3**. Set **DB_PATH** to use a different location. For the real guild, use its server ID, a fresh database and its own map roles/channels. The database checks the server ID at startup.

Back up SQLite with the process stopped, or use SQLite’s online backup facility. On restart the bot recovers current shifts and pending work, and skips expired requests. An interrupted Discord send can occasionally produce a duplicate message after a crash. Seat claims and role-ping button presses are checked against the database. If a ping fails, inspect the bot log, channel permissions, role configuration and member intent. The delivery worker retries failed jobs while they are relevant.

## Public roster and open requests

Use `/roster` to see one party’s current and upcoming shifts in the next 24 hours. The bot selects the party from the current channel, then your active booking or map role; if it is ambiguous, choose a party. Ended shifts and shifts starting 24 hours or more from now are hidden. Actual bookings replace the daily lineup once an occurrence opens, so replacements and vacancies appear without duplicate shifts. Upcoming recurring lineups are marked planned. Times default to each viewer’s local timezone; the optional timezone field shows one chosen zone. The response is private to the caller.

In any configured server, anyone can use `/cover` or `/replace`. Members without a current shift choose a configured map, enter hours and an optional platform or comment. The bot posts an open request. A guildmate can claim it without a map role. Open requests send real notifications in the configured channel and have separate seats from the scheduled rotation. Members with an active scheduled seat use the regular handoff flow.

## Missing one upcoming shift

Use `/cant_make_it`, select the dated shift (use Later week to look further ahead), and submit the optional platform note. The bot opens that one seat and keeps the recurring signup. Registered subs get first call. After five minutes the bot contacts matching /lf players, or calls them immediately if no eligible sub is found. Later /lf signups see matching openings when they register. Members can claim part of the shift or press Ping map role immediately. Replacements booked in advance get a check-in 30 minutes before their booked segment. An advance request saves the lineup and timing for that occurrence early, so later recurring edits apply to other occurrences.

Open map requests from /replace or /cover call the map’s recurring subs across all published time slots, including subs currently booked. The requester is excluded.
