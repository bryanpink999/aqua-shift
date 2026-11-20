# aqua’s shifts · Guild handbook

**Playing regularly?** Use `/sign_up`, choose DSG or FH, pick your time, then press **Join as main** for a seat or **Join as sub** to be called when someone needs help. Choose **Join this shift only** for a one-off signup. Regular signups repeat daily. Anyone in the server can sign up without a mod or map role.

**Looking for a training spot?** Use `/lf`. Enter **How long are you available for?** in hours, then **How long from now are you available?** in hours. Enter 0 to start now or 0.5 to start in 30 minutes. For example, duration 2 and delay 0.5 means you can play for two hours starting in 30 minutes. Add an optional platform note like “prefer top left.” Run it inside the map’s configured rotation thread to select that map automatically. Elsewhere, choose a map with the buttons. No map roles are needed. To look for either map, run /lf in both threads; the latest availability times apply to both. You can edit your availability or press **Stop looking**. Otherwise it expires on its own.

## Member commands

| Command | When to use it |
| --- | --- |
| `/roster` | See who has each seat, who’s signed up as a sub, and which seats are open for one map over the next 24 hours. Times use your local timezone. Only you see the result. |
| `/roster7d` | See the next seven days for one map, with dates, mains, subs and open seats. Use Next and Previous to browse pages. |
| `/sign_up` | Join a particular shift as a main or sub. Add your in-game platform, such as “bottom left,” in the optional comment. |
| `/lf` | List when you can start and how many hours you can play from that start. |
| `/cant_make_it` | Know early that you’ll miss a shift? Pick the date and shift. Press **Later week** to select a shift seven or more days ahead. The bot looks for a replacement for that occurrence and keeps your daily signup. |
| `/replace` | Leaving for the rest of your shift? Open the rest of your booking and say which platform needs filling. |
| `/cover` | Coming back? Enter how many hours you’ll be away. For a 30-minute break, enter **0.5**. The bot reserves your return and reminds you when cover ends. |

Anyone can use **/replace** or **/cover**. If you have no current seat, choose a map and enter the hours you need. This creates a separate request in the map channel.

## From reminder to handoff

1. About **30 minutes before your shift**, look for your personal mention in the map channel. Press **I’m showing up** or **I can’t make it**. If you leave it unanswered, your seat stays pending.
2. When someone needs a replacement or cover, **subs get first call**. If the opening is still there five minutes later, the bot pings matching **/lf** players. When it finds no eligible sub, it checks **/lf** immediately. For a separate map request, it looks across the map’s published recurring sub lists and skips the person asking.
3. **Urgent?** Anyone viewing an open request can press **Ping @here (thread)** immediately. Each opening allows one @here ping in its configured rotation thread. It never sends @here in a parent channel. Discord controls notification delivery based on presence and notification settings.
4. To help, press **Claim all or part**. The box asks **How long are you available for?** Enter hours from your claim start, or leave it blank for the available interval. Your /lf start time is respected. If you joined through **/lf**, your availability end time limits the claim. Any time before your start or after your finish stays open for other players. Add your platform if useful. Wait for the claim announcement before handing off in-game.

**Example:** You’re booked for DSG from 5 PM to 1 AM and use **/replace** at 7 PM. Someone claims two hours starting at 7 PM. They take **7–9 PM**, and the bot advertises **9 PM–1 AM** to subs and available /lf players. If you only need a break from 7–9 PM and plan to return, use **/cover** for two hours instead.

## For mods

- **/map_setup** connects each map to the thread where you run the command and its timetable timezone. Run it inside the DSG rotation thread with name DSG, then inside the FH thread with name FH. Forum posts count as threads. Use the existing map name when updating so its roster is kept.
- **/manage** lets an admin choose their own timezone, enter daily shift times, set the seat count for each shift, and assign members as mains or subs. For a four-person DSG party, enter **4**. Add as many daily shifts as the rotation needs. The bot tracks dates and handles shifts that cross midnight.
- Press **Publish timetable** when the draft is ready. Use **Edit timing / seats** and publish again when the schedule changes. Shifts that already have a roster keep their times. The test server allows gaps. Other servers require the schedule to cover 24 hours. Shifts may not overlap.
- Only map setup and timetable management require **Manage Server** permission. To test a real sub ping, have one person sign up as a recurring DSG sub and a different person open a DSG request. Check the public request in the configured channel for the sub’s mention.

## Moving from the role-based version

An admin runs `/map_setup` inside each existing map thread using the same map name. Allow the bot **View Channel**, **Send Messages in Threads**, **Read Message History**, and **Mention @everyone, @here, and All Roles** there. The button uses only @here. Existing mains, subs and bookings stay saved. Players using /lf before the upgrade should run it again in their desired threads to choose their maps.
