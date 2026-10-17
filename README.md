# CHP standings site

This turns the CHP spreadsheet into a website that updates itself. Every 3 hours, GitHub downloads the latest scores from Massey Ratings, recomputes the standings, weekly results and weekly prize money, and republishes the site. Nobody has to refresh anything.

The league setup lives in plain files in the `league` folder. You edit those right on the GitHub website; the site rebuilds within a couple of minutes of each edit.

## One-time setup (about 30–60 minutes)

1. **Create a GitHub account** at github.com if you don't have one. Your username becomes part of the site address.
2. **Create a repository.** Click the **+** in the top right, then **New repository**. Name it `chp`, choose **Public**, and click **Create repository**. (Free GitHub sites require a public repository; see "Things to know" below.)
3. **Upload the files.** On the new repository's page, click **uploading an existing file**. Unzip the folder I gave you, open it, select everything inside it (including the `.github` folder) and drag it all onto the upload page. Click **Commit changes**.
   - On a Mac, the `.github` folder is hidden in Finder. Press **Cmd + Shift + .** to show it.
   - Check that it worked: your repository should show a `.github` folder. If it doesn't, click **Add file → Create new file**, type `.github/workflows/update.yml` as the name, paste in the contents of that file, and commit.
4. **Turn on the website.** Go to **Settings → Pages**. Under **Source**, choose **GitHub Actions**.
5. **Run it once.** Go to the **Actions** tab. If GitHub asks, click to enable workflows. Click **Update standings** on the left, then **Run workflow**. A green check means it worked (about a minute).
6. **Open your site** at `https://YOUR-USERNAME.github.io/chp/`. Send that link to the league.

**If the run shows a red X:** click into it, click the **build** step, and copy the text it shows. Send that to me and I'll fix it. Your site isn't affected; it keeps showing the last good update.

## Editing during the season

To edit any file: open it on GitHub, click the pencil icon, make the change, and click **Commit changes**. You can also edit the `.csv` files in Excel, save as CSV, and upload them over the old ones (**Add file → Upload files**).

| When | File | What to do |
|---|---|---|
| Draft night | `league/draft.csv` | One row per pick: player, pick number, team. Team names must match Massey's spelling (see `league/d1_teams.txt`). |
| Redraft | `league/draft.csv` | Fill in `second_half_team` on the row of the team being dropped. Leave it blank for teams that are kept. |
| Any time | `league/payouts.csv` | Add prizes and entry-fee balances. Weekly prizes are added automatically, so don't enter those. Use the category `Credit/(Debt)` for entry fees and paybacks (negative = owes). |
| Before Week 2 | `league/cup.csv` | First-round Cup matchups, one row per matchup, in bracket order (the winner of row 1 plays the winner of row 2, and so on). Everything after that is automatic. |
| Rarely | `league/cup_overrides.csv` | Only if a Cup matchup needs a ruling: add the week and the player who wins it. |
| End of season | `league/hall_of_fame.csv` | Add a row for the season. |

If a drafted team name doesn't match Massey, the site still builds, and a "Data notes for the commissioner" line appears at the bottom of the site with a suggested spelling.

## New season checklist

1. In `league/settings.toml`, update `season`, and paste the new season's Massey scores link into `massey_url`. The link has an `s=` number that changes every season; it's the same link you'd use for the Excel web query.
2. Replace `league/weeks.csv` with the new week start dates. Each row is a week number, its Monday start date, the half (1 or 2), and Y/N for whether it pays a weekly prize. The last row, `Postseason`, covers the tournaments: those games count toward the season but there's no weekly prize.
3. Replace `league/draft.csv` with the new draft, clear `payouts.csv` and `cup_overrides.csv` down to the header row, and enter the new first-round Cup matchups in `cup.csv`.
4. Add any newly Division I schools to `league/d1_teams.txt`.

## How the scoring works

These match the old spreadsheet, and I checked them against the 2025–26 workbook.

- A win counts only against a Division I opponent. Every loss counts.
- Games before the first week's start date (exhibitions) don't count.
- Weekly records count all 10 of a player's teams for that half.
- Each half is scored separately. In each half, the team with the lowest win % is dropped (with equal win %, the one with more losses), and the other 9 count. The season record is first-half top 9 plus second-half top 9.
- Ties are never broken; tied players share a place, shown as "2-T". Tied players split the combined weekly money for the places they occupy.
- A tie means an identical winning percentage, so 12–6 and 10–5 are tied. This is set by `tie_rule` in `settings.toml`; changing it to `record` would count only identical W–L records as ties (how weekly money was split in past seasons).
- The Hebert Cup plays itself out over the weeks listed in `cup_weeks` in `settings.toml`. Each matchup goes to the better win % for the week (all 10 teams), then more wins, then prior week win %, then point differential (every game that week, including against non-Division I teams), then win % of the #10 pick that week, then #9, and so on. The #10 pick is the player's last row in `draft.csv`. Winners only advance once the week is final; during the week the Cup tab shows who's leading. If a matchup is still tied after every tiebreaker, the site flags it for you to settle in `cup_overrides.csv`.
- A week's prize money is added to the Money tab once the next week has started. While a week is in progress, the Weekly tab shows what each player "would win."

## Things to know

- **The repository and site are public.** Anyone with the link can see them, and the repository is visible on GitHub. It shows first names, last initials and dollar amounts. Keeping it private would need a paid GitHub plan or a different free host such as Cloudflare Pages; ask me if you want that instead.
- **GitHub pauses scheduled updates after 60 days without any edits** to a public repository. It emails you first, and one click re-enables them. Any edit (a payout, a redraft entry) resets the clock.
- **Scores come from one page on masseyratings.com,** fetched 8 times a day, which is a light load. If Massey changes the page layout, the update will fail (you'll get an email from GitHub) and the site keeps showing the last good results until it's fixed.
- KenPom isn't included, since its terms don't allow automated downloading.

## Files

- `build.py` – downloads scores and computes everything (Python, nothing to install)
- `site/index.html` – the website
- `league/` – your league setup files
- `.github/workflows/update.yml` – the schedule that runs it all
