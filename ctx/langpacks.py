"""Words of particular languages, kept in one place and apart from the code that uses them.

Nothing in the engine assumes which languages an owner writes in, or how many. Where a rule has to know a word of a
language (the word for "is" in "the password is ...", the words that say "i will send it"), it asks here, and every
pack is asked alike: no language is the main one and none is second.

PACKS is keyed by language code. A pack is a dict of small lists; any list may be left out. The lists a pack may hold:

  is               the word for "is" that can stand between a name and its value ("password is x")
  verb_last        true for a language that puts its word for "is" after the value ("<name> x <is>"), so that
                   order is read too. not a list: a property of the language
  not_a_password   what follows "password is" when nobody is giving a password away (wrong, the same, changed ...)
  everyday         everyday words, 3 to 8 plain letters: a run of words that holds one is a sentence, not a seed phrase
  account          the word for a bank account, before its number
  asks             a line that wants an answer or asks for something
  promises         the owner's own words that commit to doing something
  not_promises     what looks like a promise and is not
  done             a later line that says the thing was done
  intro            putting two people in touch
  not_found        an answer saying it did not find the thing, or is not sure
  code_word        the word for a one-time code ("code" in "your code is 123456"): six digits beside it are one
  automated        words of a message a machine sent: a code, a receipt, a delivery or bank notice, an offer

"is", "not_a_password" and "everyday" hold plain words. The rest hold pieces of a regular expression,
matched as whole words without regard to case, so a piece may hold a choice: "voy a (mandar|enviar)". Words are written
the way people type them in chat: mostly without accents, and for a language with a script of its own, also in latin
letters. A pack is small on purpose: it is a start a speaker of the language can add to, not a dictionary.

To add a language, add an entry to PACKS below, or call add() from code. Modules build their patterns inside a function
handed to on_change(), which runs at once and again after every add() or remove(): a new pack is in use from the next
line read, with nothing else to edit.
"""

PACKS = {
    "de": {
        "name": "German",
        "is": ["ist", "lautet", "sind"],
        "not_a_password": """nicht falsch ungueltig richtig korrekt gleich dasselbe dieselbe neu neue neues alt alte welches wo hier dort dein deine mein meine
            unser geaendert abgelaufen schwach stark sicher geheim leer fehlt noetig vergessen verloren nichts etwas alles aber wie schick sende sag gib
            aendern zuruecksetzen anders egal keins noch schon wieder bitte""".split(),
        "everyday": """der die das und ist nicht ein eine einen mit auf fuer von aber oder auch noch schon nur sehr mehr hier dort wann warum wie was wer wir
            ihr sie ich mich mir dich dir uns euch mein dein sein kein keine heute morgen gestern jetzt gleich dann danach vorher immer nie fast
            alles nichts etwas viel wenig ganz genau klar danke bitte hallo nein doch mal eben haben habe hast sind bin bist war waren
            kann kannst willst muss soll gehe geht komme kommt mache macht sage sagt weiss glaube""".split(),
        "account": ["konto", "kontonummer", "bankverbindung"],
        "asks": ["(kannst|koenntest|könntest|wuerdest|würdest) du", "bitte", "sag (mir )?bescheid", "(schick|sende|schreib|ruf|gib|erinner) (mir|mich)", "melde dich", "warte (auf|noch)", "gibt es (was )?neues"],
        "promises": ["ich (schicke|sende|mache|pruefe|prüfe|schaue|rufe|zahle|ueberweise|überweise|schreibe|kuemmere|kümmere)", "(schicke|sende|mache|pruefe|prüfe|zahle|ueberweise|überweise) ich (dir|euch|morgen|heute|gleich|spaeter|später)",
                     "ich (werde|will) (es |das |dir )?(schicken|senden|machen|pruefen|prüfen|anrufen|zahlen|klaeren|klären)", "lass mich (schauen|pruefen|prüfen|nachsehen)", "bis (morgen|heute abend|montag|freitag|naechste woche|nächste woche)"],
        "not_promises": ["ich (schicke|mache|zahle) (das |es )?nicht", "wenn ich (es |das )?(schicke|mache|zahle)"],
        "done": ["geschickt", "gesendet", "erledigt", "gemacht", "bezahlt", "ueberwiesen", "überwiesen", "gebucht", "bestellt", "repariert", "hab(e)? (es |ich )?(geschickt|gemacht|bezahlt)", "hier ist (es|der|die|das)",
                 "schau (mal|es dir an)"],
        "intro": [r"vorstell\w*", r"stell\w* (dich|euch|dir|ihn|sie)\b[^.!?\n]{0,40}\bvor\b", "(kennst|kennt) (du|ihr) schon", "(sprich|rede|redet) (mal )?mit", r"in kontakt (bringen|setzen)", "meld(e)? dich bei"],
        "not_found": ["(nicht|nichts) gefunden", "nicht sicher (ob|welche|welcher|welches)", "finde (es|das|ihn|sie) nicht"],
        "code_word": ["code", "bestaetigungscode", "bestätigungscode", "sicherheitscode"],
        "automated": ["bestaetigungscode", "bestätigungscode", "abbestellen", "ihre bestellung", "deine bestellung", "rechnung", "quittung", "wurde (versandt|zugestellt|gutgeschrieben|abgebucht)", "hier klicken",
                      "nur fuer kurze zeit", "nur für kurze zeit", "% rabatt", "verpasster anruf"],
    },
    "en": {
        "name": "English",
        "is": ["is", "are"],
        "not_a_password": """not wrong incorrect invalid required same correct reset changed expired weak strong there here with that what your mine the
            for and this none null true false empty missing needed optional hidden unknown protected manager field again please change todo tbd link
            page prompt policy rules hint""".split(),
        "everyday": """the and for are not but was after back been came could did does down even from gave get going gonna got had haha has her here
            him his hmm how its let lol look made may new nope our out per pls really said says see she should some take than thanks their them
            these those thx told too took via well went were which while who whole why with would yeah yes your""".split(),
        "account": ["a/c", "acc(?:t|ount)?", "routing", "aba", "beneficiary"],
        "asks": ["(can|could|will|would) (you|u)", "(pls|plz|please)", "let me know", "lmk", "(send|share|call|ping|text|tell|remind|update) me", "get back", "waiting (for|on)",
                 "(when|what time|where) (are|is|do|can|will|should)", "any (update|thoughts|news)"],
        "promises": ["i'?ll", "i will", "will (send|share|do|check|call|pay|get|update|revert|ping|look|fix|push|write|confirm|let)", "let me (check|know|see|get back|send|look|confirm|think)",
                     "(send|share|do|finish|have) (it|this|that) by", "by (tomorrow|tmrw|tonight|eod|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|the weekend)"],
        "not_promises": ["i'?ll (be|have|take|pass|miss|never|probably|maybe|see you)", "if i will", "i will not", "i won'?t"],
        "done": ["sent", "done", "shared", "attached", "paid", "transferred", "pushed", "deployed", "shipped", "fixed", "booked", "ordered", "here (you go|it is|is the)", "check (now|your)",
                 "have a look", "take a look"],
        "intro": [r"intro\w*", r"connect\w*", "meet", "met", "put (you|u|him|her|them) in touch", r"loop\w* (you|u|him|her|them)? ?in", "reach out to", "talk to", "speak (to|with)",
                  r"cc\b", "e-?meet"],
        "not_found": ["could not find", "not sure (this|which|that)"],
        "code_word": ["code"],
        "automated": ["otp", "verification code", "unsubscribe", "your order", "invoice", "receipt", "has been (shipped|delivered|credited|debited)", "a/c", "txn", "click here", "limited time", "% off", "webinar",
                      "reacted .{0,12} to", "liked a message", "sent an attachment", "missed (voice|video)? ?call"],
    },
    "es": {
        "name": "Spanish",
        "is": ["es", "son"],
        "not_a_password": """no incorrecta incorrecto invalida invalido correcta correcto misma mismo nueva nuevo vieja viejo cual donde esta esa aquella tuya
            mia suya cambiada obligatoria olvidada perdida segura debil fuerte nada algo todo para pero como enviame mandame dime pasame cambiar
            restablecer vacia falta otra igual secreta ninguna""".split(),
        "everyday": """que los las una uno por con para pero como mas muy este esta esto ese esa eso hay soy eres estoy estas tengo tienes tiene hola vale
            bien bueno ahora luego antes cuando donde porque pues tambien nada todo toda algo aqui alla hoy ayer manana nunca siempre casi mismo otro
            otra ellos ella nos les mio tuyo suyo hacer hace hice dijo voy vas vamos quiero puedo puedes creo gracias jaja claro entonces mucho
            poco sobre desde hasta entre sin tan asi cual quien""".split(),
        "account": ["cuenta", "clabe"],
        "asks": ["(puedes|podrias|podrías|puede|podria|podría)", "por favor", "porfa", "(avisame|avísame|mandame|mándame|enviame|envíame|pasame|pásame|llamame|llámame|dime)", "me (avisas|mandas|envias|envías|pasas|llamas|dices)",
                 "(sigo|estoy) esperando", "alguna (novedad|noticia)"],
        "promises": ["te (lo |la )?(mando|envio|envío|paso|aviso|llamo|pago|confirmo)", "(lo|la) (hago|reviso|mando|envio|envío|arreglo|veo)", "voy a (mandar|enviar|revisar|hacer|llamar|pagar|ver|confirmar|arreglar|escribir)",
                     "(mañana|manana|luego|ahorita) (te|lo|la) (mando|envio|envío|paso|aviso|llamo|hago|reviso)", "dejame (ver|revisar|confirmar)", "déjame (ver|revisar|confirmar)", "para (mañana|manana|el lunes|el viernes|la tarde|la noche)"],
        "not_promises": ["no (te )?(lo |la )?(mando|envio|envío|hago|voy a)", "si (te )?(lo |la )?(mando|envio|envío|hago)"],
        "done": ["enviado", "enviada", "hecho", "pagado", "transferido", "arreglado", "reservado", "pedido", "ya (esta|está|quedo|quedó|lo mande|lo mandé|lo envie|lo envié|lo hice|pague|pagué)", "(te|se) lo (mande|mandé|envie|envié|pase|pasé)",
                 "aqui (esta|está|tienes)", "aquí (esta|está|tienes)", "(echale|échale) un (ojo|vistazo)"],
        "intro": [r"present(o|ar|arte|arles|e)\b", "te presento", "(conoce|conozcas|conocer) a", r"pon(er|go|erlos|erte) en contacto", "(habla|hablar|hables) con", r"contacta\w*", "les escribo a (los dos|ambos)"],
        "not_found": ["no (lo |la )?(encontre|encontré|encuentro)", "no (aparece|estoy seguro|estoy segura)"],
        "code_word": ["codigo", "código", "clave"],
        "automated": ["codigo de verificacion", "código de verificación", "darse de baja", "tu pedido", "su pedido", "factura", "recibo", "ha sido (enviado|entregado|abonado|cargado)", "haz clic aqui", "haz clic aquí",
                      "tiempo limitado", "% de descuento", "llamada perdida"],
    },
    "fr": {
        "name": "French",
        "is": ["est", "sont"],
        "not_a_password": """pas faux fausse incorrect incorrecte invalide correct correcte bon bonne pareil meme nouveau nouvelle ancien ancienne lequel
            quel ici la ton ta mon notre votre change expire faible fort forte secret vide manque requis oublie perdu rien quelque tout mais comme envoie
            donne dis passe changer reinitialiser autre encore deja toujours aucun""".split(),
        "everyday": """les des une est pas que qui pour avec dans sur par mais donc aussi encore deja tres plus moins bien ici voila quand
            pourquoi comment quoi nous vous ils elles moi toi lui mon ton son notre votre leur cette ces tout tous rien quelque beaucoup peu
            hier demain apres avant toujours jamais presque merci salut bonjour oui non alors bon bah ouais avoir suis etes sont etait
            peux peut veux veut dois doit vais vas allons fais fait dit sais crois""".split(),
        "account": ["compte", "numero de compte", "numéro de compte", "rib"],
        "asks": ["(tu peux|peux-tu|pourrais-tu|vous pouvez|pouvez-vous)", "s'il (te|vous) pla[iî]t", "stp", "svp", "(dis|tiens)-moi", "(envoie|appelle|rappelle|ecris|écris|previens|préviens)-moi", "tu me (dis|envoies|rappelles|tiens au courant)",
                 "j'attends", "des nouvelles"],
        "promises": ["je (t'|vous |te |le |la )?(envoie|appelle|rappelle|paie|confirme|regarde|verifie|vérifie|fais|ecris|écris)", "je vais (envoyer|appeler|regarder|verifier|vérifier|faire|payer|confirmer|ecrire|écrire|voir)",
                     "je (m'en|m'en) occupe", "laisse-moi (voir|verifier|vérifier|regarder)", "(d'ici|avant) (demain|ce soir|lundi|vendredi|la semaine prochaine)"],
        "not_promises": ["je ne (vais|peux) pas", "si je (l'envoie|le fais|paie)"],
        "done": ["envoye", "envoyé", "envoyee", "envoyée", "c'est fait", "paye", "payé", "vire", "viré", "reserve", "réservé", "commande", "commandé", "repare", "réparé", "je (l'ai|t'ai|vous ai) (envoye|envoyé|fait|paye|payé)",
                 "(le|la) voici", "jette un (oeil|œil|coup d'oeil|coup d'œil)"],
        "intro": [r"pr[eé]sente[rsz]?\b", "je (te|vous) pr[eé]sente", "(tu connais|vous connaissez) (deja |déjà )?", "(parle|parlez|parles) (a|à|avec)", r"mettre? en (contact|relation)", "contacte"],
        "not_found": ["(pas|rien) trouv[eé]", "je ne (trouve|suis) pas", "pas (sur|sûr|sure|sûre) (que|de|lequel|laquelle)"],
        "code_word": ["code", "code de verification", "code de vérification"],
        "automated": ["code de verification", "code de vérification", "se desabonner", "se désabonner", "votre commande", "ta commande", "facture", "recu", "reçu", "a ete (expedie|livre|credite|debite)", "a été (expédié|livré|crédité|débité)",
                      "cliquez ici", "duree limitee", "durée limitée", "% de reduction", "% de réduction", "appel manque", "appel manqué"],
    },
    "hi": {
        "name": "Hindi",
        "is": ["hai", "hain"],
        "verb_last": True,
        "not_a_password": """kya nahi galat bhej bata batao daal dalo pata yaad wahi sahi kuch nahin kaisa kaise kaha kahan kidhar mila dala daala bheja
            bhejo diya liya hota hoti bhool bhul yahi kaun kiska mera tera uska apna naya purana""".split(),
        "everyday": """hai nahi kya bhi toh aaj aap abhi accha agar apna aur baad bahut bas bhai bola bolo dena ghar haan hoga hota hote hoti hum hun inka
            iska isko jana kaam kab kabhi kaise kal kar karna karo karte kaun kisi kitna kitne kiya koi kuch kyu kyunki lekin lena liye mat matlab mein
            mera meri mujhe pehle phir raha rahe rahi raho saath sab sirf tera teri tha theek thi tujhe tum unka uska usko wahi wala wali woh yaar yahi""".split(),
        "account": ["khata"],
        "asks": ["(bata|batao|bataiye|bata do|bata de|bhej do|bhej de|bhejo|kar do|kar de|dekh lo|dekh le|call kar|reply kar|kab|kitna|kahan|kaun)"],
        "promises": ["(bhej|kar|bata|dekh|de|likh|puch) (dunga|doonga|deta hu+n?|deta hoon|lunga|loonga|leta hu+n?)", "(bhejta|karta|batata|dekhta|likhta|puchta) hu+n?", r"kal (tak )?(bhej|kar|bata|de)\w*",
                     "(bhejunga|karunga|bataunga|dekhunga|likhunga|aaunga|milta hu+n?)"],
        "not_promises": ["nahi (bhejunga|karunga|dunga|bhej|kar) ?(paunga|sakta)?", "agar (main )?(bhej|kar|de) (du|dun|diya)"],
        "done": ["ho gaya", "kar diya", "bhej diya", "de diya", "bata diya", "dekh liya", "likh diya"],
        "intro": [r"milwa\w*", r"mila\w*", r"baat kar\w*"],
        "not_found": ["nahi (mila|dikh)"],
        "code_word": ["code", "kod"],
        "automated": ["otp hai", "aapka order", "aapka otp", "khate (me|mein) (jama|credit)", "khate se (kata|debit)", "yahan click kare", "seemit samay", "% ki chhoot", "missed call aaya"],
    },
    "id": {
        "name": "Indonesian",
        "is": ["adalah", "yaitu", "itu"],
        "not_a_password": """salah benar betul tidak bukan sama baru lama yang apa mana dimana itu ini punya saya kamu kita sudah belum diganti diubah wajib
            lupa hilang aman lemah kuat kosong kurang lain rahasia kirim kirimin kasih bilang ganti ubah nanti dulu tolong minta harus perlu masih juga
            saja tadi""".split(),
        "everyday": """yang dan ini itu dengan untuk dari pada tidak nggak gak bukan ada saya aku kamu dia kita kami mereka sudah udah belum akan bisa mau
            harus juga lagi saja aja sama atau tapi kalau kalo karena jadi nanti besok kemarin hari sekarang tadi dulu banyak sedikit semua apa siapa
            kapan dimana gimana kenapa iya oke makasih terima kasih tolong maaf dong deh sih nih kok lah sangat banget masih pernah sering baru lama
            bikin buat bilang lihat pergi pulang""".split(),
        "account": ["rekening", "norek", "no rek"],
        "asks": ["tolong", "(bisa|boleh) (kamu|lu|lo|minta|tolong|kirim|bantu|cek)", "(kabari|kabarin|kirimin|kirimkan|telepon|hubungi|ingatkan|ingetin) (aku|saya|gue|gw)", "minta (tolong|dikirim|kabar)", "ditunggu",
                 "(ada|gimana) (kabar|update)"],
        "promises": ["(nanti|besok|sebentar lagi) (aku |saya |gue |gw )?(kirim|kabari|kabarin|cek|bayar|telepon|kerjakan|kerjain|urus|lihat)", "(aku|saya|gue|gw) (akan|bakal|mau) (kirim|cek|bayar|kabari|kabarin|kerjakan|kerjain|urus|telepon)",
                     "(aku|saya|gue|gw) (kirim|kabari|kabarin|cek|bayar) (nanti|besok|malam ini|sore ini)", "(aku|saya|gue|gw) cek dulu", "paling lambat (besok|senin|jumat|minggu depan)"],
        "not_promises": ["(nggak|gak|tidak|ga) (akan|bakal|bisa|jadi)", "kalau (aku|saya|gue|gw) (kirim|bayar)"],
        "done": ["(sudah|udah) (dikirim|kukirim|kirim|dibayar|bayar|selesai|beres|ditransfer|transfer|dicek|dipesan|diperbaiki)", "terkirim", "selesai", "beres", "ini dia", "silakan (dicek|cek|dilihat)", "coba (cek|lihat)"],
        "intro": [r"kenal(in|kan|an)\b", r"perkenalkan\w*", r"(hubungi|kontak|ngobrol sama|ngobrol dengan|bicara dengan)", "saling kenal"],
        "not_found": ["(tidak|nggak|gak) (ketemu|ditemukan|yakin)"],
        "code_word": ["kode", "kode verifikasi"],
        "automated": ["kode verifikasi", "kode otp", "berhenti berlangganan", "pesanan (anda|kamu)", "tagihan", "struk", "telah (dikirim|diterima|dikreditkan|didebit)", "klik di sini", "waktu terbatas",
                      "diskon %", "panggilan tak terjawab"],
    },
    "ja": {
        "name": "Japanese",
        "is": ["desu", "da", "wa", "です", "は"],
        "verb_last": True,
        "not_a_password": """chigau machigai machigatta tadashii onaji atarashii furui dore doko koko soko watashi anata bokuno kawatta kireta yowai tsuyoi
            anzen himitsu kara nai hitsuyou wasureta nakushita nani nanika zenbu demo okutte oshiete kudasai onegai kaeru kaete risetto betsu mada mou
            mata hitotsu wakaranai shiranai dame muri hontou tabun""".split(),
        "everyday": """desu masu kara dake demo sore kore koko soko ima kyou ashita kinou watashi boku anata kimi kare minna nani dare itsu doko naze
            sou kedo dakara soshite mata mou mada totemo sugoi chotto takusan sukoshi zenbu nanika arigatou arigato gomen onegai kudasai
            ohayou genki wakatta shiranai iku kuru suru shita shite itta kita miru mita taberu nomu kaeru omou iru aru nai naru natta dekiru hoshii
            suki kirai hontou tabun zettai yappari tokoro toki hito koto mono""".split(),
        "account": ["kouza", "kouza bangou", "口座", "口座番号"],
        "asks": ["onegai(shimasu)?", "kudasai", "(oshiete|okutte|renraku shite|denwa shite|mite|kakunin shite) (kudasai|kureru|kurenai|moraeru)?", "matte(ru|imasu)", "(nanika|nani ka) (shinten|renraku)", "お願いします", "ください", "教えて"],
        "promises": ["(ashita|ato de|kondo|sugu|kyou juu ni) (okuru|okurimasu|renraku suru|renraku shimasu|kakunin suru|kakunin shimasu|harau|haraimasu|yaru|yarimasu|denwa suru)",
                     "(okurimasu|renraku shimasu|kakunin shimasu|haraimasu|yatte okimasu|shirabete okimasu)", "(okutte|yatte|mite|shirabete) oku", "送ります", "確認します", "連絡します"],
        "not_promises": ["(okuranai|yaranai|harawanai|dekinai)", "moshi (okuttara|haraeba)"],
        "done": ["okutta", "okurimashita", "yatta", "yarimashita", "haratta", "haraimashita", "furikonda", "yoyaku shita", "chuumon shita", "naoshita", "dekita", "owatta", "kore desu", "mite (kudasai|ne)", "送りました", "完了"],
        "intro": [r"shoukai\w*", "(hanashite|hanashi shite|atte) (mite|kudasai)", "tsunagu", "tsunaide", "renraku shite mite", "紹介"],
        "not_found": ["mitsukara(nai|nakatta)", "wakara(nai|nakatta)", "(yoku )?wakarimasen", "見つかりません"],
        "code_word": ["koudo", "ninshou koudo", "コード"],
        "automated": ["ninshou koudo", "kakunin koudo", "haishin teishi", "go chuumon", "seikyuusho", "ryoushuusho", "(hassou|haitatsu|nyuukin|hikiotoshi) (sare|shi)mashita", "kochira wo kurikku", "kikan gentei", "% ofu",
                      "fuzai chakushin", "認証コード", "ご注文"],
    },
    "pt": {
        "name": "Portuguese",
        "is": ["é", "são", "sao"],
        "not_a_password": """nao errada errado incorreta invalida correta certa mesma mesmo nova novo antiga velha qual onde essa esta aquela sua minha nossa
            trocada alterada obrigatoria esquecida perdida segura fraca forte nada algo tudo para mas como manda envia fala passa trocar mudar redefinir
            vazia falta outra igual secreta nenhuma""".split(),
        "everyday": """que nao uma uns com para por mas como mais muito este esta isso isto esse essa aqui ali tem tenho temos sou estou voce voces ele ela
            eles elas meu minha seu sua nosso ola tudo bem bom boa agora depois antes quando onde porque pois tambem nada algo hoje ontem amanha nunca
            sempre quase mesmo outro outra fazer faz fiz disse vou vai vamos quero posso pode acho obrigado valeu kkk claro entao pouco sobre desde ate
            entre sem tao assim qual quem ainda""".split(),
        "account": ["conta", "agencia e conta", "agência e conta"],
        "asks": ["(pode|poderia|consegue|voce pode|você pode)", "por favor", "pfv", "pfvr", "me (avisa|manda|envia|passa|liga|fala|lembra|atualiza)", "(to|tô|estou) (esperando|aguardando)", "(alguma|tem) (novidade|noticia|notícia)"],
        "promises": ["vou (mandar|enviar|ver|fazer|ligar|pagar|conferir|checar|confirmar|arrumar|escrever|resolver)", "(te|lhe) (mando|envio|aviso|ligo|pago|passo|confirmo)",
                     "(mando|envio|faço|faco|vejo|pago|confiro|resolvo) (amanhã|amanha|hoje|já|ja|mais tarde|depois)", "deixa (eu |que eu )?(ver|conferir|checar|confirmar)", "(até|ate) (amanhã|amanha|segunda|sexta|o fim do dia)"],
        "not_promises": ["(não|nao) vou", "se eu (mandar|enviar|fizer|pagar)"],
        "done": ["enviado", "enviada", "feito", "pago", "transferido", "arrumado", "resolvido", "reservado", "mandei", "enviei", "paguei", "(já|ja) (fiz|mandei|enviei|paguei|resolvi|está|esta|foi)",
                 "(aqui|segue) (está|esta|o|a)", "(dá|da) uma olhada"],
        "intro": [r"apresent(o|ar|ei|a)\b", r"te apresento", "(conhecer|conheça|conheca) (o|a)", r"colocar? (voces|vocês|os dois) em contato", "(fala|falar|fale) com", r"contat(o|a|ar) (o|a)"],
        "not_found": ["(não|nao) (achei|encontrei|aparece|tenho certeza)"],
        "code_word": ["codigo", "código"],
        "automated": ["codigo de verificacao", "código de verificação", "cancelar inscricao", "cancelar inscrição", "seu pedido", "fatura", "recibo", "foi (enviado|entregue|creditado|debitado)", "clique aqui",
                      "tempo limitado", "% de desconto", "chamada perdida"],
    },
}

KEYS = ("is", "not_a_password", "everyday", "account", "asks", "promises", "not_promises", "done", "intro", "not_found", "code_word", "automated")
FLAGS = ("verb_last",)
_hooks = []


def codes():
    """The languages there are packs for, in the order of their codes."""
    return sorted(PACKS)


def words(key):
    """Every entry of one list, over every pack, each once, packs in the order of their codes."""
    out = []
    for code in codes():
        out += [str(w) for w in PACKS[code].get(key) or [] if str(w).strip()]
    return list(dict.fromkeys(out))


def verb_last():
    """The words for "is" of the languages that put it after the value, each once."""
    out = []
    for code in codes():
        if PACKS[code].get("verb_last"):
            out += [str(w) for w in PACKS[code].get("is") or [] if str(w).strip()]
    return list(dict.fromkeys(out))


def alt(key, default="(?!)"):
    """The entries of one list as the inside of a regular-expression choice, longest first so a longer piece is not cut
    short by a shorter one that starts it. `default` (which never matches) when no pack has the list."""
    got = sorted(words(key), key=lambda w: (-len(w), w))
    return "|".join(got) if got else default


def on_change(build):
    """Run build() now, and again whenever a pack is added, changed or removed. A module makes its patterns in build(),
    so they always hold every pack there is. Returns build, so it can be used as a decorator."""
    _hooks.append(build)
    build()
    return build


def changed():
    """Tell every module that PACKS was edited in place."""
    for build in list(_hooks):
        build()


def add(code, pack):
    """Add a language, or add to one: the lists given are joined to the lists the pack already has. In use at once."""
    code = str(code).strip().lower()
    if not code or not isinstance(pack, dict):
        raise ValueError("a pack is a language code and a dict of lists")
    have = PACKS.setdefault(code, {})
    for key, value in pack.items():
        if key == "name":
            have["name"] = str(value)
        elif key in FLAGS:
            have[key] = bool(value)
        elif key in KEYS:
            have[key] = list(dict.fromkeys(list(have.get(key) or []) + [str(w) for w in value]))
        else:
            raise ValueError("no such list: %s. lists: %s" % (key, ", ".join(KEYS + FLAGS)))
    changed()
    return have


def remove(code):
    """Take a language out again (a test, or an owner who wants none of it)."""
    gone = PACKS.pop(str(code).strip().lower(), None)
    changed()
    return gone
