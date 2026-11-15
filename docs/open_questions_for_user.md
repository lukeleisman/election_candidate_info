# Open questions for the user (collected 2026-11-14, for a separate review session)

Each item: candidate / file, what was seen, the decision needed. Sources: the Google social rerun
(`data/endorsements/candidate_campaign_sites_google_social_rerun.csv`, rows have matching OPEN QUESTION
notes; raw results in `data/raw/google_search/<id>_s.txt`) unless stated. Agents append new batches at the end.

## Page / rules (affect many rows)
1. **Government accounts in "Largest following".** Official office accounts (e.g. Johnson's ChicagosMayor on
   X/Facebook/TikTok/LinkedIn; the Treasurer office's accounts; many alderman office pages) count toward
   the summary's largest-following column right now. Count them, or campaign/personal accounts only?
2. **Government sites in `ward_office_url`.** quigley.house.gov (MAYOR-00-003) and the chicago.gov Office of
   the Mayor page (MAYOR-00-006) were put in the ward-office column though neither is a ward office. Keep, move
   to other_site_urls, or a new link kind ("government office")?
3. **Link source order.** `build_candidate_links.py` lists sources user > google > google_social_rerun > first
   pass. Listing order only. Keep?
4. **Ballot-website accounts that may be someone else** are shown on the page until checked (Greenlaw,
   Scrutchens, Kenny Williams below). Hide unverified ones before publishing?
5. **Privacy: Zelle link with an encoded email** (ALD-13-001 Cacciottolo, other_site_urls; also carries
   `utm_source=chatgpt.com`). Drop it, keep it unpublished, or keep as is?
6. **Endorsement it GAVE** (ALD-49-004 Su, first round): endorsements_seen_raw holds Su's endorsement of
   Gibbons (25th). Keep as a note or drop? (from the 2026-11-14 handoff)

## Mayor / citywide
7. **MAYOR-00-005 Giannoulias: "Endorsed By" logos** on alexiforus.com (no captions; names guessed by WebFetch
   from image file names): Chicago Tribune, Daily Herald, Planned Parenthood Illinois, Democratic Party of
   Illinois, AFL-CIO, PersonalPAC. Probably from his 2026 Secretary of State race. Enter as cycle `older`,
   check by hand, or skip? Also: UA Plumbers Local 130 post in the same row.
8. **MAYOR-00-006 Johnson: endorsement lead** AFGE Local 789 (Instagram post in results, not loaded). Fetch?
9. **MAYOR-00-010 Kitover:** mayorkitover.com (first round) not in results now; new domains
   johnkitoverchicago.com and johnkitovermayor.com behind a bot check (403), unconfirmed. Which is current?
10. **MAYOR-00-012 Pappas:** mariapappas.net is her Cook County Treasurer committee site (no mayor-race
    mention; ActBlue pappas2022/2018). Count as her campaign site, or keep needs_confirmation?
11. **MAYOR-00-013 Cardenas:** Block Club story 2026-10-29 "Mayoral Candidate's Website Exposed Voting
    History Of ..." (title cut off) names him. For the future "Reporting on this race" section?
12. **MAYOR-00-016 Maronto:** site says "We are pivoting our focus back to Oasis" and they "aren't
    TRADITIONALLY working on campaigning for Mayor." Note on the page that the campaign may be inactive?
13. **MAYOR-00-008 Nee:** Bluesky handle spelled "lisaneeforchiago" on her site; recorded as given. OK?
14. **CLERK-00-001 Valencia:** /endorsements shows endorsers only as 7 images (needs a person to read them).
15. **TREAS-00-001 Bruce Leon:** only accounts from his congressional run (Instagram @bruceleonforcongress,
    LinkedIn). Show them? Lead: he endorsed Phil Andrew (IL-9, Jan 2026) — endorsement he gave, not received.
16. **MAYOR-00-015 Zoe Ma:** Green Party US Facebook group post promoting her (not worded as an endorsement).

## Wards 1-18
17. **ALD-04-001 Robinson / ALD-05-001 Yancy:** first round's campaign accounts (Robinson @lamontrobinsonfor4,
    @votelamontjrobinson; Yancy @YancyForThe5th, @yancyfor5thward, ActBlue) not in results now; only office
    accounts appeared. The page still shows both rounds. Fine?
18. **ALD-05-002 Greenlaw:** Instagram @itsgreenlaw and Facebook @rgreenlaw92, snippets don't mention the
    race. Same person?
19. **ALD-06-001 Scrutchens:** first round Instagram @voteforallyson, now @itsallysonrenee. Both hers?
    (first round also had an Adrienne McFarland endorsement snippet)
20. **ALD-06-003 Hall:** williamhallfor6.com (first round) still not in Google results. Still his?
21. **ALD-07-002 Pendleton:** second Facebook URL facebook.com/1215002105028388/ with the same page title.
    Same page or a second one?
22. **ALD-07-003 Gunn-Ward:** 10 individual endorsers on her /view-endorsements page (realtors, business
    owners), not yet entered. One read as "Brugzgul" and the firm as "Bruzgul": check spelling. Enter
    individuals as endorsements (endorser_type person)?
23. **ALD-07-004 Radyn Franc:** site names only "Radyn" and "7th Ward"; surname only in outside links
    (forwardparty.com/radynfranc, buymeacoffee.com/francfamily). Accept as his site?
24. **ALD-07-005 Cher Phillips:** a result snippet "His name is Casey Mark Smagala." Unknown relevance; ignore?
25. **ALD-08-001 Mack:** WebFetch truncated the home page; social links / endorsements lower down may be
    missed. Look in Chrome?
26. **ALD-08-002 Harris:** office site aldermanmichelleharris.com has a "2027 Campaign Kickoff" post
    (2026-08-10). Count the office site as her campaign site too?
27. **ALD-09-001 Beale:** ward09.com looks like an office site but says "Paid for by Citizen's to Elect Anthony
    A. Beale." Campaign or office column?
28. **ALD-09-003 Kenny Williams (ambiguous):** people4kenny.com is a Kenny (Kenneth) Williams who ran for IL
    Senate District 14 (March 2026 primary); no aldermanic mention; links ActBlue kenny-williams-1, Facebook
    kenny.williams.3133 (5.2K+). For same person: ninthward.blog "Williams has previously sought office in the
    area"; his LinkedIn mentions the 9th Ward. Address check: CBOE filing 10910 S Wabash Ave, 60628; senate
    site has no street address. Same person?
29. **ALD-13-002 Cepek:** CBOE objection list (2026-11-04) shows case 27-EB-ALD-018 (objector NICHOLAS
    JANETEAS III) by his name. Check ballot_status? Google removed 15 results (DMCA) from his search.
30. **ALD-13-003 Keith Judge:** X @KMJforChiMayor from a 2023 mayoral write-in. Same person? (address check
    would need the CBOE filing address vs a people-search 60629 listing)
31. **ALD-12-003 Carlos Sanchez:** several same-named people (a Police District Council member, a CPD
    sergeant); nothing ties any to the candidate. Leave none_found?
32. **ALD-13-001 Cacciottolo:** endorsement leads Ald. Marty Quinn, Eddie Guillen (snippets). Fetch?
33. **ALD-14-001 Gutierrez:** jeylugutierrez.com not in results; office site chicago14.com has a certificate
    error (not bypassed). Rerun row is needs_confirmation (first round found). Check by hand?
34. **ALD-14-002 Reyes:** Facebook event "A Night in Support of Raul Reyes for 14th Ward Alderman"
    (2026-12-04) and a post from page id 61596160144747 (name not shown). Lead: Alma Anaya endorsed Gutierrez
    in 2023.
35. **ALD-15-001 Lopez:** raymondalopez.com does not name the 2027 race (only a "ReElect" image file name).
    Accept as campaign site?
36. **ALD-16-002 Fletcher:** Instagram fletcherforbetter post says "first Alderwoman of Chicago's 22nd Ward"
    while naming 16th Ward neighborhoods. Lead: LaRonda Jones endorsement.
37. **ALD-16-003 Blackmond:** Facebook post "SHES RUNNING 16th ward" names "Cheryl Blackman". Same person?
38. **ALD-16-004 Eddie Johnson III:** Sun-Times "ENDORSEMENT: Eddie Johnson III for 16th Ward alderman" is
    from 2019. eddie16thward.com (first pass) still not in Google results.
39. **ALD-17-002 Greenleaf:** votegreenleaf.com was found from plain text in a Facebook video snippet ("Visit
    votegreenleaf. com"), then loaded ("Paid for by Friends of Raynetta Greenleaf for 17th Ward Alderperson").
    OK to record a site found that way?
40. **ALD-17-005 Steward:** Facebook post "James Steward for alderman of the 17th Ward Chicago" from page id
    61594720079780 (name not shown). His campaign page?
41. **ALD-18-002 Barksdale:** his Facebook page is named "Alderman Joshua Barksdale" though he's a
    challenger. Flag on the page?

## Process notes (no decision needed unless you want one)
- One agent fixed its own row after append.py (ALD-05-002, removed a display name it had guessed from a
  handle). Another restored trailing spaces the Write tool stripped from Links sections (checked lengths).
- javascript_tool output is cut at ~800 characters; agents read the Links output in slices and join them.

## Wards 18-20 (batch 8, ALD-18-004..ALD-20-004)
42. **ALD-20-001 Jeanette Taylor:** taylorfor20th.com (first round) not in results; ward20th.com doesn't link
    it. Rerun row is found on the office site only. Is taylorfor20th.com still her 2027 site?
43. **ALD-20-003 Maddox:** maddox4ward20.com is the 2023-race site (2023 post and calendar, no 2027). Kept as
    found (judgment call, like round one). Show it, or mark it as an older site? A third-party video snippet
    ("served the 34th Ward for 20+ years") doesn't fit her.
44. **ALD-20-002 Gebre:** site links Instagram @candidate_for_20th_ward; round one's results showed
    @candidate_for_alderperson. Same person, renamed?
45. **ALD-20-004 Andre Smith:** ActBlue andresmithfor20 and Facebook andre4cook (a Cook County run?). Neither
    shown to be for 2027. Show them?
46. **ALD-18-006 Galloway:** Instagram post from personal-looking @tonic.galloway. Hers / campaign?
47. **ALD-19-002 Jillian Robinson:** new accounts "Forwardbound with Jillian Robinson" (Facebook, Instagram,
    Threads). Block Club cites "her campaign" site, still not found.
48. **ALD-19-001 Ross:** endorsement lead Ald. Matt O'Shea (Beverly Review, 2026-09-10). Fetch and enter?
    (Also a stale 2023 Chicago Crusader endorsement for Maddox, ALD-20-003.)

## Wards 20-25 (batch 9, ALD-20-005..ALD-25-001)
49. **ALD-24-001 / ALD-24-003 Monique Scott (duplicate filing):** aldermanscott.com, office or campaign site
    (it doesn't say)? Facebook @CitizensForScott sounds like a campaign committee.
50. **ALD-25-001 Aida Flores:** aidafor25.com lists endorsements David Orr and Sue Sadlowski Garza (read on the
    page). Enter them in endorsements_manual.csv?
51. **ALD-20-005 Egeston:** her site names the race only in logo alt text, spelled "Jarquitta". Kept as found.
52. **ALD-24-002 Anderson:** a Rich RL Lucci post has "Anderson ... 24th Ward" in its title but a snippet
    about a "7th District Alderman" race. Ignore?
53. **ALD-24-004 Kiisha Smith:** Block Club (2026-11-11) says she chairs the 10th Police District Council
    (settles round one's question). An ISBE committee result appeared; its ID was lost with the query string.
54. **ALD-22-001 Bahena:** 22ndward.org lists her as Ald. Rodriguez's chief of staff; not recorded as her
    office site. Instagram @hijadelavillita: show it?

## Wards 25-27 (batch 10, ALD-25-002..ALD-27-002; agent stopped at the usage limit before its report, rows complete)
55. **ALD-26-001 Fuentes:** "2027 Re-Election endorsements" on jessiefor26thward.com, names read by WebFetch
    from image file names / link URLs (no visible text): Omar Aquino, Graciela Guzmán, Delia Ramirez, Lilian
    Jimenez, Will Guzzardi, Tara Stamps, Jessica Vásquez, Sierra Club Chicago Group, Rossana Rodriguez Sanchez,
    Anthony Quezada, Mijente. Check by eye and enter? (The handoff listed Fuentes's page as needing Chrome.)
56. **ALD-25-003 Watkins:** his site links facebook.com/profile.php?id=61588918181420; not recorded because
    of the query string. Record profile.php?id= URLs when a site gives them in full?
57. **ALD-25-006 Chacon:** lead, Michael Crowner Facebook post "Supporting Miguel's campaign for Chicago city
    hall" (personal support, not an endorsement).
58. **ALD-25-007 Willman:** a 2019 release on a Nubia Willman (director, Office of New Americans) is likely
    her but not confirmed on the campaign site. Fine to leave unlinked?

## Ward 27 (final batch, ALD-27-003..ALD-27-004)
59. **ALD-27-004 Olas:** two Facebook URLs, facebook.com/people/Dan-Olas/61587836511094/ (linked from his
    site) and facebook.com/DanOlas27/ (results). Same page? His "files nominating petitions" post again shows a
    snippet about Nate Cornell. Round one's Italian American Police Association endorsement snippet did not
    reappear.
60. **ALD-27-003 Cornell:** the agent rewrote its own row after append.py (replaced a guessed Facebook URL with
    the profile.php?id=61593345454032 link from his site). File checked afterward: 102 rows, 22 columns, ids
    unique.

## Post-author review queue
61. **76 new post authors** with blank verdicts in `data/endorsements/social_post_authors_review.csv` (121 rows
    total), added by `make social-accounts` from the rerun raw files. Present 10 at a time as a plain numbered
    list with a suggested verdict each (candidate / not candidate / already listed), as before.
