# Full-chapter Hindi narration: Solo Leveling Ch.108 (movie-style).
# V2: natural Hindustani (Hindi+Urdu+English mix as most Indians speak) — no shuddh/bookish words.
# Resume: stdin lines "voices/NNN_KEY_Idx.mp3 <dur>" skip regeneration. JSON -> stdout.
import asyncio
import json
import sys

import edge_tts

VOICES = {
    "NAR":  ("hi-IN-MadhurNeural", "-5%",  "+0Hz"),    # narrator, deep storyteller
    "JIN":  ("hi-IN-MadhurNeural", "-8%",  "-12Hz"),   # Sung Jinwoo, calm low
    "GUN":  ("hi-IN-MadhurNeural", "-20%", "-30Hz"),   # Go Gunhee, old gravelly
    "BAEK": ("hi-IN-MadhurNeural", "-5%",  "-18Hz"),   # Baek Yoonho, gruff warm
    "ADAM": ("hi-IN-MadhurNeural", "+5%",  "+8Hz"),    # Adam White, slick
    "CON":  ("hi-IN-MadhurNeural", "-3%",  "+15Hz"),   # Michael Connor, smooth
    "F1":   ("hi-IN-SwaraNeural",  "+0%",  "+0Hz"),    # netizen female
    "F2":   ("hi-IN-SwaraNeural",  "-12%", "-10Hz"),   # older/emotional female
    "F3":   ("hi-IN-SwaraNeural",  "+12%", "+25Hz"),   # young girl netizen
    "M1":   ("hi-IN-MadhurNeural", "+10%", "+30Hz"),   # young male netizen
}

# (page, voice, text) — everyday Hindustani, in playback order
SEGMENTS = [
    (0,  "NAR",  "Solo Leveling. Chapter ek sau aath. Jeju ke baad."),
    (1,  "NAR",  "Jis din Jeju island ki jang khatam hui... poori duniya ki nazar wahin thi."),
    (2,  "NAR",  "Aur us bheed ke beechon-beech khada tha... Sung Jinwoo."),
    (3,  "NAR",  "Haath mein ek safed phool tha... aur dil mein un sab ka bojh, jo kabhi wapas nahi aaye."),
    (4,  "F1",   "Wah... main to shabd hi bhool gayi."),
    (4,  "NAR",  "Jeju raid khatam hote hi... duniya sirf isi ki baat kar rahi thi."),
    (5,  "F3",   "Itna saara jaanwar bulana... bilkul namumkin tha."),
    (5,  "M1",   "Uske jaanwaron ko ladte dekh kar... mera das saal purana cancer theek ho gaya, bhai!"),
    (5,  "F1",   "Wo hai hi sabse mahan... The GOAT!"),
    (6,  "NAR",  "Lekin behas bhi chhid gayi thi... kya Jinwoo ko National Level Hunter hona chahiye tha?"),
    (6,  "F1",   "Hona to chahiye... National Level!"),
    (6,  "M1",   "Are nahi yaar... utna bhi khaas nahi hai."),
    (6,  "F3",   "Akela S-rank dungeon clear kiya hai... skill to zyada hi hai."),
    (7,  "NAR",  "Darasal... Jeju hi Sung Jinwoo ka debut tha."),
    (7,  "F1",   "Second awakening hua hoga... tabhi itna strong hua hai."),
    (7,  "M1",   "E-rank se itna powerful... kaise mumkin hai?"),
    (8,  "NAR",  "Poora desh is raid se juda tha... khabrein, channels, social media... har taraf sirf Jinwoo."),
    (9,  "NAR",  "Lekin tareef ke saath... taane bhi aaye."),
    (9,  "NAR",  "Andhere mein sainkdon aankhein... seedhe us par gadi thi."),
    (9,  "F2",   "Agar Jinwoo shuru se aata... to shayad Min Byung-gu marta hi nahi..."),
    (10, "NAR",  "Logon ko yakeen tha... agar wo pehle aata, to itne log nahi marte."),
    (10, "F2",   "Aadhe mein hi aaya wo... aakhir kyun?"),
    (11, "NAR",  "Hazaaron log uske bachav mein khade the... lekin ilzaam ka jawab kisi ke paas nahi tha."),
    (11, "NAR",  "Yaad mein phool... ek-ek kar rakhe ja rahe the."),
    (12, "NAR",  "Kyunki sach yahi tha... us jang mein khoon beha tha."),
    (12, "NAR",  "Hawa mein sirf khamoshi thi... aur safed phoolon ki khushboo."),
    (13, "NAR",  "Aur phoolon ke us samandar mein... ek muskurata chehra tha. Min Byung-gu."),
    (14, "NAR",  "Aaj poora desh... apne shaheedo ko yaad kar raha tha."),
    (15, "NAR",  "Memorial ke saamne akela khada tha... Sung Jinwoo."),
    (16, "NAR",  "Uske chehre pe jo likha tha... wo shabdon mein nahi samata."),
    (17, "NAR",  "Waqt... ruk sa gaya tha."),
    (18, "NAR",  "Peeche khadi thi wo maa... jiska beta kabhi ghar nahi lauta."),
    (19, "NAR",  "Aur Jinwoo ki aankhon mein sirf ek sawaal ghoom raha tha... kya main der se aaya tha?"),
    (20, "NAR",  "Tabhi bheed mein se... ek jana-pehchana chehra nikla. Baek Yoon-ho... White Tiger Guild ka master."),
    (21, "BAEK", "Main hamesha maanta tha... koi akela poori jang nahi jeet sakta."),
    (22, "NAR",  "Do hunters... aamne-saamne."),
    (23, "BAEK", "Lekin haal ke hadson ke baad..."),
    (24, "BAEK", "Lagta hai... main galat tha."),
    (25, "BAEK", "Sar upar rakhiye, Mr. Sung."),
    (25, "NAR",  "Uski awaaz mein... ek ajeeb apnapan tha."),
    (26, "BAEK", "Aap hi wo the... jinhone is sadme ko khatam kiya."),
    (27, "BAEK", "Shukriya."),
    (27, "NAR",  "Ek aansu... aur sab keh diya."),
    (28, "NAR",  "Aur bheed ke us paar se... kisi ki nazrein Jinwoo se takra gayin. Cha Hae-in."),
    (28, "NAR",  "Wo nazar keh rahi thi... aap theek to hain na?"),
    (29, "NAR",  "Memorial ke aangan mein har taraf bas dukh tha... kale kapdon mein lipte sab log, haath pakde khade the."),
    (30, "NAR",  "Cha Hae-in ki aankhein jhuki thi... unke bheetar bhi dard tha."),
    (31, "NAR",  "Achanak... uski aankh chamki."),
    (31, "NAR",  "Wo aankhein... sirf usi ko dhoond rahi thi."),
    (32, "NAR",  "Wahin doosri taraf... Jinwoo kuch soch hi raha tha ki..."),
    (33, "NAR",  "Aasman ki taraf uthta safed monument... hazaaron ki kurbaani ki gawah khada tha."),
    (33, "NAR",  "Hawa mein pankh ud rahe the... jaise rohein aaj shaant ho gayi hon."),
    (34, "NAR",  "Memorial hall ki deewar... phoolon se dhak chuki thi."),
    (35, "NAR",  "Paanchve Jeju raid mein paanch hazaar se zyada hunters shamil hue... aur saat sau se zyada aam logon ko bhi bulana pada."),
    (35, "NAR",  "Ye sirf raid nahi thi... ye jang thi. Insaanon ki... us teele ki raani ke khilaf."),
    (36, "NAR",  "Chausath awakened aur battis civilians... kul karib sau log nahi lote."),
    (36, "NAR",  "Aankde sunte hi dil daha jata hai... phir bhi..."),
    (37, "NAR",  "Pichhle chaar koshishon se tulna karein... to ye sabse kam the."),
    (38, "NAR",  "Udhar khuli chhat ke neeche... table pe do log baithe the. Aur peeche sakht security."),
    (39, "GUN",  "To... apni guild banane ka plan hai tumhara?"),
    (39, "NAR",  "Guild... hunters ki apni team. Sawaal seedha tha."),
    (40, "GUN",  "Certified S-rank ko guild master license ki zaroorat nahi hoti. Bas association ko phone kar dena."),
    (41, "GUN",  "Baaki hum sambhal lenge."),
    (41, "JIN",  "...Okay."),
    (42, "NAR",  "Jinwoo ne mann hi mann socha... S-rank ke fayde bhi to check karne chahiye."),
    (43, "GUN",  "Waise... tumne Jeju island pe barrier banaya tha, na?"),
    (44, "NAR",  "Ek pal ke liye... sab thehar gaya."),
    (45, "JIN",  "Maaf kijiye... kya?"),
    (45, "NAR",  "Sawaal itna achanak tha... ki Jinwoo hakka-bakka reh gaya."),
    (46, "GUN",  "Safai karne gaye crews sab behosh mile... aur sabki yaaddasht gayab thi."),
    (47, "GUN",  "A aur B rank samet, Knights Guild wale bhi. Shayad barrier banakar bhool gaye ho?"),
    (47, "JIN",  "Nahi... maine aisa kuch nahi kiya."),
    (47, "NAR",  "Poore island pe chhaya ye raaz... kisi ko kuch yaad nahi tha."),
    (48, "GUN",  "Hmm... theek hai."),
    (49, "NAR",  "Chairman ki nazron mein shak tha... lekin zubaan pe sabar."),
    (50, "GUN",  "Mujhe laga bhi tha... tumne kiya nahi hoga."),
    (50, "JIN",  "Waise wo hunters aur soldiers... kya bol rahe the?"),
    (51, "GUN",  "Behosh hone se pehle kuch yaad nahi... koi jaadui taqat bhi pakad mein nahi aayi."),
    (52, "NAR",  "Dono chup ho gaye... aur us khamoshi mein ek ajeeb dar tha."),
    (53, "JIN",  "Kahin ye... cheentiyon ka chhoda hua jaal to nahi?"),
    (53, "NAR",  "Jinwoo ke dimaag mein tasveeren daudne lagin..."),
    (54, "NAR",  "Phir wahi khamoshi..."),
    (55, "NAR",  "Tabhi ek agent aakar... baat tod deta hai."),
    (56, "GUN",  "Mujhe nikalna hoga... mehmaan pehle hi pahunch gaya hai."),
    (56, "JIN",  "Aapka samay dene ke liye shukriya."),
    (57, "NAR",  "Jinwoo lautne nikal pada... lekin jaate-jaate usse ek nayi mulaqaat karni thi."),
    (58, "NAR",  "Meeting khatam ho chuki thi... lekin din ka safar abhi baaki tha."),
    (59, "NAR",  "Parking lot mein... ek ajnabi ne awaaz lagayi."),
    (60, "ADAM", "Maaf kijiye... kya aap Mr. Sung Jinwoo hain?"),
    (60, "NAR",  "Suit mein taiyar Jinwoo thaka hua tha... lekin pura sambhla hua."),
    (61, "ADAM", "Aapse milkar khushi hui, Mr. Sung."),
    (62, "ADAM", "Mera naam hai Adam White... Federal Bureau of Hunters ka senior officer."),
    (62, "JIN",  "Federal Bureau of Hunters?"),
    (63, "NAR",  "Business card haath mein lete hue Jinwoo ne socha... America?"),
    (64, "NAR",  "America ka bureau... seedhe usse milne aaya tha."),
    (65, "ADAM", "Achanak aane ke liye maafi chahiye... aapko dhoondhna aasan nahi tha."),
    (66, "NAR",  "Jinho ki baat sahi nikli... yahi wo foreigner tha."),
    (68, "JIN",  "Mere se kya kaam hai tumhara?"),
    (68, "ADAM", "Main aapko kuch information dena chahta hoon."),
    (69, "NAR",  "Adam ki muskaan mein hi... jawab chhupa tha."),
    (70, "ADAM", "Ye information na koi desh de sakta hai... na hi koi organization."),
    (71, "ADAM", "Siway... hamare."),
    (71, "NAR",  "Poori duniya... siway unke."),
    (72, "NAR",  "Jinwoo chup raha... aur uski chuppi hi uska jawab thi."),
    (73, "JIN",  "Aisi information... mujhse kyun share karna chahte ho?"),
    (74, "ADAM", "Aapke jaise khaas logon se rishta... hamare liye faydemand hai."),
    (75, "ADAM", "Akela aana tay tha... lekin Jeju raid ne hamare deputy director ko impress kar diya."),
    (76, "ADAM", "Wo aapse aamne-saamne milna chahte hain. Gaadi ready hai... chalenge?"),
    (76, "NAR",  "Bina bataye mulaqaat... history mein pehli baar."),
    (77, "NAR",  "Van ke darwaze khule... andar kadam rakhne ka waqt tha."),
    (78, "NAR",  "Jinwoo ne ek pal ke liye socha..."),
    (79, "JIN",  "Information bharosemand hai kya? ...Soch kar phone karunga."),
    (79, "NAR",  "Darwaza band hua... faisla baad ke liye."),
    (80, "ADAM", "Main bhool gaya tha... aap to chess ke khiladi hain."),
    (81, "ADAM", "Par yaad rakhiye... asli player apne cards kabhi nahi dikhata."),
    (81, "NAR",  "Adam ki baatein... hawa mein latki rah gayin."),
    (82, "NAR",  "Gaadi mein baithte hue Adam ne bas do shabd kahe..."),
    (82, "ADAM", "Ek upgrader..."),
    (83, "ADAM", "Jo ek awakened ki taqat badha sakta hai... kabhi suna hai?"),
    (83, "NAR",  "Upgrader... koi aisa insaan, jo doosron ki taqat badal sakta hai."),
    (84, "NAR",  "Jinwoo ki aankhein phati ki phati rah gayin..."),
    (85, "NAR",  "Gaadi chal padi... aur Jinwoo ke dimaag mein sirf ek shabd goonj raha tha. Upgrader."),
    (86, "NAR",  "Shehar ki sadkon pe kaali gaadi daud rahi thi..."),
    (87, "NAR",  "Kuch der baad... gaadi ek badi si building ke saamne ruki."),
    (88, "NAR",  "Ek khamosh pal..."),
    (89, "NAR",  "Federal Bureau of Hunters... America."),
    (90, "NAR",  "Unchi building... aur golden design wala bada darwaza."),
    (91, "NAR",  "Darwaza khula... andar swagat ke liye ek aadmi khada tha."),
    (91, "CON",  "Aapse milkar khushi hui. Main hoon Michael Connor... Federal Bureau of Hunters ka deputy director."),
    (93, "JIN",  "Namaste... main Sung Jinwoo."),
    (94, "NAR",  "Saath khade translator ne muskura kar kaha... main aapka translation karunga."),
    (95, "CON",  "Mr. Sung... main seedhi baat karta hoon."),
    (96, "CON",  "Ye rahe immigration ke kagzaat."),
    (96, "NAR",  "Sofe ke saamne baithkar... Connor ne file kholi."),
    (97, "NAR",  "File table par fisalti hui aayi..."),
    (98, "CON",  "Aamtaur par inmein ek-do saal lag jate hain... par aapke liye hum exception karenge."),
    (99, "CON",  "Bas aap kahiye... aur ek second mein aap America ka citizen."),
    (99, "NAR",  "Ek second... bas ek second. Aur poori duniya badal sakti thi."),
    (100, "NAR", "Lekin citizenship ka lalach... Jinwoo ko chhoo bhi nahi paya tha."),
    (100, "JIN", "Mr. White ne kaha tha... aapke paas mere liye koi information hai."),
    (101, "CON", "Ek awakened jo... doosre awakened ki taqat badha sakta hai. Upgrader."),
    (102, "JIN", "Kya sach mein mumkin hai? Kisi hunter ki ability... upgrade ho sakti hai?"),
    (102, "NAR", "Sawaal seedha tha... aur jawab Jinwoo ko sach mein chahiye tha."),
    (103, "CON", "Jiske paas ye taqat hai... wo isi waqt is kamre mein maujood hai. Ms. Selner ko bulaiye."),
    (103, "NAR", "Upgrader... isi kamre mein? Jinwoo ki saans ruk gayi."),
    (104, "NAR", "Aur Connor ke honton pe... ek chaalaak muskaan aa gayi."),
    (105, "NAR", "Agli hi pal... darwaze se high heels ki awaaz goonji. Clack... clack..."),
    (105, "NAR", "Har kadam... Jinwoo ki dhadkan se takra raha tha."),
    (106, "NAR", "Kadam kareeb aate gaye..."),
    (107, "NAR", "Aur phir... sab kuch thehar gaya."),
    (108, "NAR", "Aur Jinwoo ki aankhon mein neeli chamak utar aayi... kahani yahin rukti hai. Jaari rahega..."),
    (109, "NAR", "Solo Leveling... chapter ek sau aath samapt. Agla part jald."),
]

SILENT_MOOD = {13, 14, 15, 16, 17, 18, 19, 33, 34, 52, 84, 104, 105, 106, 107, 108}
ACT_BREAK = {29, 58, 87}
INTRO = 10.0
TAIL = 0.55
GAP = 1.2
END = 22.0


async def gen(idx, page, key, text, sem, done):
    fname = f"{page:03d}_{key}_{idx:03d}.mp3"
    if fname in done:
        return page, key, fname, done[fname]
    voice, rate, pitch = VOICES[key]
    async with sem:
        last_end = 0.0
        for attempt in range(3):
            try:
                tts = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
                async for chunk in tts.stream():
                    if chunk["type"] == "WordBoundary":
                        last_end = (chunk["offset"] + chunk["duration"]) / 1e7
                await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(f"voices/{fname}")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"FAIL p{page} {key}: {e}", file=sys.stderr)
                    return None
                await asyncio.sleep(2)
    return page, key, fname, round(last_end + TAIL, 3)


async def main():
    done = {}
    for line in sys.stdin:
        parts = line.split()
        if len(parts) == 2 and parts[0].endswith(".mp3"):
            done[parts[0].split("/")[-1].split("\\")[-1]] = float(parts[1])
    print(f"resuming: {len(done)} already done", file=sys.stderr)
    sem = asyncio.Semaphore(3)
    results = await asyncio.gather(
        *(gen(i, p, k, t, sem, done) for i, (p, k, t) in enumerate(SEGMENTS))
    )
    out = []
    t = INTRO
    prev_page = None
    for r in results:
        if r is None:
            continue
        page, key, fname, dur = r
        if prev_page is not None:
            if page != prev_page:
                t += 5.0 if page in ACT_BREAK else (3.5 if page in SILENT_MOOD else GAP)
            else:
                t += 0.4
        out.append({"page": page, "key": key, "file": fname, "start": round(t, 3), "dur": dur})
        t += dur
        prev_page = page
    total = round(t + END, 3)
    sys.stdout.write(json.dumps({"total": total, "segments": out}, indent=1))


asyncio.run(main())
