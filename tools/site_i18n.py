# -*- coding: utf-8 -*-
"""Every word of the public page, in the six languages the app speaks.

The page is built in English and carries the rest with it, the way the
app does: one file, and the words are swapped in place. The questions
are not here - those come from the app's own FAQ, already translated,
and taking them from anywhere else would let the two drift apart.

Each table is keyed by language and never by position, and the checks at
the bottom refuse to build a page where a language is short an entry.
That is not hypothetical: a list edited by position is exactly how the
German and Spanish strings once ended up in each other's places.
"""

LANGS = ["en", "ru", "es", "fr", "de", "ja"]

# What the switcher shows. The same short forms the app uses.
SHORT = {"en": "En", "ru": "Ру", "es": "Es", "fr": "Fr",
         "de": "De", "ja": "日本"}

# The setting named in the second known problem is written into
# __SETTING__ from the app's own translations, so the page never invents
# a name for a switch the app labels differently.

UI = {
"en": {
    "h1": "Gamepad Drift assist for Forza Horizon",
    "sub": "Telemetry based steering assist, for smooth, stable and "
           "enjoyable drifting in the Forza Horizon series. 100% Free To "
           "Use!",
    "ver": "Free to use - source available - Windows - version __VER__",
    "dl": "Download",
    "src": "Source on GitHub",
    "lang": "Language",
    "h_what": "What it does",
    "l_what": "Not a screenshot. This is the app's own page, built from "
              "the same source as the exe, with made-up telemetry behind "
              "it. Every tab and slider works - try them.",
    "shotnote": "Driving data is invented for the preview. Everything "
                "else is the real thing.",
    "h_start": "Getting started",
    "l_start": "A real first run, in the order it happens.",
    "prev": "Previous",
    "next": "Next",
    "h_q": "Questions",
    "l_q": "Every one of these was somebody's actual problem.",
    "h_road": "What is coming",
    "l_road": "Roughly in the order it is likely to happen. None of it is "
              "a promise with a date on it.",
    "h_known": "Known problems",
    "l_known": "Everything here is real, and none of it is a surprise to "
               "us. It is being worked on.",
    "oline": "Stop fighting your own car.",
    "osub": "Switch it on, keep your foot in it, and enjoy the roads of "
            "Horizon the way you imagined them.",
},
"ru": {
    "h1": "Ассист дрифта на геймпаде для Forza Horizon",
    "sub": "Помощь в рулении на основе телеметрии игры — ровный, стабильный и приятный дрифт в серии Forza Horizon. Полностью бесплатно!",
    "ver": "Бесплатно — исходники открыты — Windows — версия __VER__",
    "dl": "Скачать",
    "src": "Исходники на GitHub",
    "lang": "Язык",
    "h_what": "Что он делает",
    "l_what": "Это не скриншот. Перед вами страница самого приложения, собранная из того же кода, что и exe, с выдуманной телеметрией под ней. Все вкладки и ползунки работают — попробуйте.",
    "shotnote": "Данные о поездке для превью выдуманы. Всё остальное настоящее.",
    "h_start": "Установка",
    "l_start": "Настоящий первый запуск, шаг за шагом.",
    "prev": "Назад",
    "next": "Далее",
    "h_q": "Вопросы",
    "l_q": "Каждый из них — чья-то реальная проблема.",
    "h_road": "Что дальше",
    "l_road": "Примерно в том порядке, в каком до этого дойдут руки. Ни один пункт не обещание со сроком.",
    "h_known": "Известные проблемы",
    "l_known": "Всё перечисленное — правда, и ничто из этого для нас не новость. Мы этим занимаемся.",
    "oline": "Хватит бороться с собственной машиной.",
    "osub": "Включите ассист, держите газ и наслаждайтесь дорогами Horizon такими, какими вы их себе представляли.",
},
"es": {
    "h1": "Asistente de derrape con mando para Forza Horizon",
    "sub": "Asistencia de dirección basada en la telemetría del juego, "
           "para derrapes suaves, estables y disfrutables en la saga Forza "
           "Horizon. ¡Totalmente gratis!",
    "ver": "Gratis - código disponible - Windows - versión __VER__",
    "dl": "Descargar",
    "src": "Código en GitHub",
    "lang": "Idioma",
    "h_what": "Qué hace",
    "l_what": "No es una captura. Es la propia pantalla de la app, "
              "construida con el mismo código que el exe y con "
              "telemetría inventada por detrás. Todas las "
              "pestañas y los deslizadores funcionan: pruébalos.",
    "shotnote": "Los datos de conducción de la vista previa son "
                "inventados. Todo lo demás es real.",
    "h_start": "Primeros pasos",
    "l_start": "Un primer arranque real, en el orden en que ocurre.",
    "prev": "Anterior",
    "next": "Siguiente",
    "h_q": "Preguntas",
    "l_q": "Cada una fue el problema real de alguien.",
    "h_road": "Lo que viene",
    "l_road": "Más o menos en el orden en que es probable que ocurra. "
              "Nada de esto es una promesa con fecha.",
    "h_known": "Problemas conocidos",
    "l_known": "Todo esto es real y nada nos sorprende. Estamos en ello.",
    "oline": "Deja de pelearte con tu propio coche.",
    "osub": "Enciéndelo, no levantes el pie y disfruta de las "
            "carreteras de Horizon como las imaginabas.",
},
"fr": {
    "h1": "Assistant de drift à la manette pour Forza Horizon",
    "sub": "Une assistance de direction basée sur la télémétrie "
           "du jeu, pour un drift fluide, stable et agréable dans la "
           "série Forza Horizon. Entièrement gratuit !",
    "ver": "Gratuit - code disponible - Windows - version __VER__",
    "dl": "Télécharger",
    "src": "Code sur GitHub",
    "lang": "Langue",
    "h_what": "Ce qu'il fait",
    "l_what": "Ce n'est pas une capture. C'est l'écran de "
              "l'application elle-même, construit à partir du "
              "même code que l'exe, avec une télémétrie "
              "inventée derrière. Tous les onglets et tous les "
              "curseurs fonctionnent : essayez-les.",
    "shotnote": "Les données de conduite de l'aperçu sont "
                "inventées. Tout le reste est réel.",
    "h_start": "Pour commencer",
    "l_start": "Un vrai premier lancement, dans l'ordre où il se "
               "déroule.",
    "prev": "Précédent",
    "next": "Suivant",
    "h_q": "Questions",
    "l_q": "Chacune a été le problème réel de quelqu'un.",
    "h_road": "La suite",
    "l_road": "À peu près dans l'ordre où cela devrait "
              "arriver. Rien ici n'est une promesse datée.",
    "h_known": "Problèmes connus",
    "l_known": "Tout ce qui suit est réel, et rien ne nous surprend. "
               "Nous y travaillons.",
    "oline": "Arrêtez de vous battre avec votre propre voiture.",
    "osub": "Lancez-le, gardez le pied dedans et profitez des routes de "
            "Horizon telles que vous les imaginiez.",
},
"de": {
    "h1": "Drift-Assistent für den Controller in Forza Horizon",
    "sub": "Lenkhilfe auf Basis der Spiel-Telemetrie - für ruhige, "
           "stabile und schöne Drifts in der Forza-Horizon-Reihe. "
           "Komplett kostenlos!",
    "ver": "Kostenlos - Quellcode einsehbar - Windows - Version __VER__",
    "dl": "Herunterladen",
    "src": "Quellcode auf GitHub",
    "lang": "Sprache",
    "h_what": "Was er macht",
    "l_what": "Kein Screenshot. Das ist die Oberfläche der App selbst, "
              "aus demselben Code wie die exe gebaut, mit erfundener "
              "Telemetrie dahinter. Jeder Reiter und jeder Regler "
              "funktioniert - probier sie aus.",
    "shotnote": "Die Fahrdaten in der Vorschau sind erfunden. Alles andere "
                "ist echt.",
    "h_start": "Erste Schritte",
    "l_start": "Ein echter erster Start, in der Reihenfolge, in der er "
               "abläuft.",
    "prev": "Zurück",
    "next": "Weiter",
    "h_q": "Fragen",
    "l_q": "Jede davon war das echte Problem von jemandem.",
    "h_road": "Was kommt",
    "l_road": "Ungefähr in der Reihenfolge, in der es wohl passieren "
              "wird. Nichts davon ist ein Versprechen mit Datum.",
    "h_known": "Bekannte Probleme",
    "l_known": "Alles hier ist real, und nichts davon überrascht uns. "
               "Wir arbeiten daran.",
    "oline": "Hör auf, gegen dein eigenes Auto zu kämpfen.",
    "osub": "Einschalten, auf dem Gas bleiben und die Straßen von "
            "Horizon so genießen, wie du sie dir vorgestellt hast.",
},
"ja": {
    "h1": "Forza Horizon 向けゲームパッド用ドリフトアシスト",
    "sub": "ゲームのテレメトリーを使ったステアリング補助。Forza Horizon シリーズで、滑らかで安定した気持ちのいいドリフトを。完全無料です。",
    "ver": "無料 - ソース公開 - Windows - バージョン __VER__",
    "dl": "ダウンロード",
    "src": "GitHub のソース",
    "lang": "言語",
    "h_what": "できること",
    "l_what": "スクリーンショットではありません。exe と同じコードから作られたアプリ本体の画面で、裏では架空のテレメトリーが動いています。タブもスライダーもすべて動くので、触ってみてください。",
    "shotnote": "プレビューの走行データは架空のものです。それ以外はすべて本物です。",
    "h_start": "はじめかた",
    "l_start": "実際の初回起動を、起こる順番どおりに。",
    "prev": "戻る",
    "next": "次へ",
    "h_q": "よくある質問",
    "l_q": "どれも誰かが実際にぶつかった問題です。",
    "h_road": "これから",
    "l_road": "だいたい実現しそうな順番です。どれも期日を約束するものではありません。",
    "h_known": "既知の問題",
    "l_known": "ここに書いたことはすべて事実で、こちらも把握しています。順次対応しています。",
    "oline": "自分の車と戦うのは、もう終わりです。",
    "osub": "オンにして、アクセルを踏んだまま、思い描いていたとおりの Horizon の道を楽しんでください。",
},
}

FEATURES = {
"en": [
    ("Catches the slide, you keep the drift",
     "Countersteer arrives as the car steps out and eases away as it comes "
     "back, so a drift holds instead of snapping into a spin."),
    ("Steps aside the moment you disagree",
     "Steer against it and the wheel is yours. It never fights you for it, "
     "and it stays quiet entirely until the car is actually sliding."),
    ("Smooth, not twitchy",
     "Steady through the transitions, and it will not start a pendulum of "
     "its own when a slide swings back through straight."),
    ("Five sliders, each doing one thing",
     "Strength, damping, the shape of the stick, how fast it answers, and "
     "the speed below which it leaves you alone entirely."),
    ("It shows you what it is doing",
     "Your own input and the assisted one side by side, live, with the "
     "speed and the rate the game is talking at."),
    ("Works when your buttons do not",
     "On some machines a hidden controller costs you gears and camera. One "
     "switch hands every button back, and the FAQ takes you to it."),
    ("Nothing to install by hand",
     "One exe. Everything it needs is inside it and sets itself up on first "
     "run, and it hands your controller back exactly as it found it."),
    ("It leaves when you ask it to",
     "One button removes the drivers, clears what was added to HidHide and "
     "deletes its own settings. Nothing of it is left behind."),
    ("Six languages, and it fits your screen",
     "English, Russian, Spanish, French, German and Japanese throughout. "
     "Light and dark, and a scale from 90 to 150 percent."),
],
"ru": [
    ("Ловит занос, дрифт остаётся вам",
     "Контрруль приходит, как только машину срывает, и уходит, когда она возвращается: занос держится, а не срывается в разворот."),
    ("Отходит в сторону, как только вы против",
     "Поверните против — руль ваш. Он не борется с вами и вообще молчит, пока машина не пошла в скольжение."),
    ("Плавно, без дёрганья",
     "Спокоен в перекладках и не раскачивает машину сам, когда занос проходит через прямую."),
    ("Пять ползунков, каждый об одном",
     "Сила, демпфирование, форма стика, скорость отклика и порог, ниже которого ассист вообще не вмешивается."),
    ("Показывает, что именно делает",
     "Ваш ввод и итоговый — рядом, в реальном времени, вместе со скоростью и частотой, с которой говорит игра."),
    ("Работает, даже когда кнопки — нет",
     "На части машин скрытый геймпад отбирает передачи и камеру. Один переключатель возвращает все кнопки, а FAQ ведёт прямо к нему."),
    ("Ничего не нужно ставить руками",
     "Один exe. Всё нужное внутри и настраивается при первом запуске, а геймпад возвращается ровно в том виде, в каком был."),
    ("Уходит, когда попросите",
     "Одна кнопка удаляет драйверы, убирает записи в HidHide и стирает собственные настройки. После неё не остаётся ничего."),
    ("Шесть языков и подгонка под экран",
     "Английский, русский, испанский, французский, немецкий и японский — везде. Светлая и тёмная темы, масштаб от 90 до 150 процентов."),
],
"es": [
    ("Atrapa el derrape, tú lo mantienes",
     "El contravolante llega en cuanto el coche se va y se retira cuando "
     "vuelve, así el derrape se sostiene en lugar de convertirse en "
     "trompo."),
    ("Se aparta en cuanto no estás de acuerdo",
     "Gira en contra y el volante es tuyo. Nunca te lo disputa, y se queda "
     "callado del todo mientras el coche no derrape."),
    ("Suave, no nervioso",
     "Estable en las transiciones, y no se pone a mecer el coche por su "
     "cuenta cuando el derrape pasa por el centro."),
    ("Cinco deslizadores, cada uno con una tarea",
     "Fuerza, amortiguación, la curva del stick, la rapidez con que "
     "responde y la velocidad por debajo de la cual te deja del todo en "
     "paz."),
    ("Te enseña lo que está haciendo",
     "Tu propia entrada y la asistida, una al lado de la otra y en directo, "
     "con la velocidad y la frecuencia a la que habla el juego."),
    ("Funciona aunque tus botones no",
     "En algunos equipos, ocultar el mando te cuesta las marchas y la "
     "cámara. Un interruptor devuelve todos los botones, y las "
     "preguntas te llevan hasta él."),
    ("Nada que instalar a mano",
     "Un solo exe. Todo lo que necesita va dentro y se configura en el "
     "primer arranque, y te devuelve el mando tal y como lo encontró."),
    ("Se va cuando se lo pides",
     "Un botón quita los controladores, borra lo que se añadió "
     "a HidHide y elimina sus propios ajustes. No queda nada suyo."),
    ("Seis idiomas, y se adapta a tu pantalla",
     "Inglés, ruso, español, francés, alemán y "
     "japonés en toda la app. Claro y oscuro, y escala del 90 al 150 "
     "por ciento."),
],
"fr": [
    ("Il rattrape le glissement, le drift reste à vous",
     "Le contre-braquage arrive dès que la voiture part et s'efface "
     "quand elle revient : le drift tient au lieu de partir en "
     "tête-à-queue."),
    ("Il s'efface dès que vous n'êtes pas d'accord",
     "Braquez à l'inverse et le volant est à vous. Il ne vous le "
     "dispute jamais, et il reste totalement silencieux tant que la voiture "
     "ne glisse pas."),
    ("Doux, pas nerveux",
     "Stable dans les transferts, et il ne lance pas de pendule à lui "
     "tout seul quand le glissement repasse par le droit."),
    ("Cinq curseurs, un rôle chacun",
     "Force, amortissement, courbe du stick, vitesse de réaction, et "
     "l'allure sous laquelle il vous laisse entièrement tranquille."),
    ("Il montre ce qu'il fait",
     "Votre entrée et celle assistée côte à côte, "
     "en direct, avec la vitesse et la cadence à laquelle le jeu "
     "parle."),
    ("Il marche même quand vos boutons non",
     "Sur certaines machines, une manette masquée vous coûte les "
     "vitesses et la caméra. Un seul réglage rend tous les "
     "boutons, et la FAQ vous y emmène."),
    ("Rien à installer à la main",
     "Un seul exe. Tout ce qu'il lui faut est dedans et se met en place au "
     "premier lancement, et il vous rend la manette exactement comme il "
     "l'a trouvée."),
    ("Il s'en va quand vous le demandez",
     "Un bouton retire les pilotes, efface ce qui a été "
     "ajouté à HidHide et supprime ses propres réglages. Il "
     "ne reste rien de lui."),
    ("Six langues, et il s'adapte à votre écran",
     "Anglais, russe, espagnol, français, allemand et japonais "
     "partout. Clair et sombre, et une échelle de 90 à 150 pour "
     "cent."),
],
"de": [
    ("Fängt den Ausbruch, der Drift bleibt deiner",
     "Das Gegenlenken kommt, sobald das Heck ausbricht, und geht "
     "zurück, sobald es sich fängt: Der Drift hält, statt in "
     "den Dreher zu kippen."),
    ("Tritt zur Seite, sobald du anderer Meinung bist",
     "Lenke dagegen, und das Rad gehört dir. Er kämpft nie darum "
     "und bleibt völlig still, solange das Auto nicht rutscht."),
    ("Weich, nicht zappelig",
     "Ruhig in den Lastwechseln, und er schaukelt das Auto nicht von "
     "selbst auf, wenn der Drift durch die Gerade schwingt."),
    ("Fünf Regler, jeder für genau eine Sache",
     "Stärke, Dämpfung, Kennlinie des Sticks, "
     "Reaktionsgeschwindigkeit und das Tempo, unterhalb dessen er dich "
     "völlig in Ruhe lässt."),
    ("Er zeigt, was er tut",
     "Deine Eingabe und die unterstützte nebeneinander, live, samt "
     "Tempo und der Rate, mit der das Spiel sendet."),
    ("Läuft auch, wenn deine Tasten es nicht tun",
     "Auf manchen Rechnern kostet ein versteckter Controller Gänge und "
     "Kamera. Ein Schalter gibt alle Tasten zurück, und die Fragen "
     "führen dich hin."),
    ("Nichts von Hand zu installieren",
     "Eine exe. Alles Nötige steckt darin und richtet sich beim ersten "
     "Start selbst ein, und deinen Controller gibt er genau so "
     "zurück, wie er ihn vorgefunden hat."),
    ("Er geht, wenn du es sagst",
     "Ein Knopf entfernt die Treiber, räumt die Einträge in "
     "HidHide weg und löscht die eigenen Einstellungen. Von ihm "
     "bleibt nichts zurück."),
    ("Sechs Sprachen, und er passt auf deinen Bildschirm",
     "Englisch, Russisch, Spanisch, Französisch, Deutsch und Japanisch "
     "durchgehend. Hell und dunkel, und eine Skalierung von 90 bis 150 "
     "Prozent."),
],
"ja": [
    ("滑り出しを受け止め、ドリフトはあなたのもの",
     "車が流れ出した瞬間にカウンターが入り、戻り始めると自然に抜けます。ドリフトはスピンに変わらず続きます。"),
    ("あなたが逆らえば、すぐに引く",
     "逆に切ればステアリングはあなたのものです。取り合いにはならず、車が滑っていない間は何もしません。"),
    ("滑らかで、神経質にならない",
     "振り返しでも落ち着いていて、ドリフトが直進を通り抜けるときに自分から車を揺すり始めることはありません。"),
    ("5つのスライダー、それぞれ役割はひとつ",
     "効きの強さ、減衰、スティックのカーブ、反応の速さ、そしてこの速度以下では一切手を出さないという境目。"),
    ("何をしているかが見える",
     "自分の入力と補正後の入力を並べてリアルタイムに表示。速度と、ゲームがデータを送ってくる頻度も一緒に。"),
    ("ボタンが効かなくなっても動く",
     "環境によっては、パッドを隠すとギアやカメラが使えなくなります。スイッチひとつで全ボタンが戻り、FAQがその場所まで案内します。"),
    ("手作業のインストールはなし",
     "exeがひとつだけ。必要なものはすべて中に入っていて、初回起動で自分で準備します。コントローラーは元どおりの状態で返します。"),
    ("頼めば、ちゃんと出ていく",
     "ボタンひとつでドライバーを削除し、HidHideに追加した設定を戻し、自分の設定ファイルも消します。何も残りません。"),
    ("6か国語、画面にも合わせられる",
     "英語・ロシア語・スペイン語・フランス語・ドイツ語・日本語にすべて対応。ライトとダーク、表示倍率90〜150%。"),
],
}

# Only the words. Which screenshot belongs to which step stays in the
# builder, where the files are.
STEPS = {
"en": [
    ("Download &amp; Launch",
     "One file, and nothing to install. Take the latest release and run it. "
     "Windows asks for administrator once - that is the moment the two "
     "drivers go in."),
    ("Let it set itself up",
     "Both drivers are inside the exe, so nothing is downloaded on your "
     "machine. The steps run themselves and say where they are up to. If "
     "Windows wants a restart, a driver has asked for one, and the app "
     "opens again by itself afterwards."),
    ("Note down what it asks for",
     "The last setup step is the only thing the assist cannot do for you: "
     "the game has to be told to send its telemetry. The values are on "
     "screen - Data Out on, IP 127.0.0.1, port 20777 - and the app waits "
     "here until they arrive."),
    ("Set it in the game",
     "Forza keeps these under <b>Settings &rarr; HUD and Gameplay</b>, at "
     "the very bottom of the list, under Telemetry. One more setting "
     "matters and lives somewhere else entirely: <b>Settings &rarr; "
     "Difficulty &rarr; Steering</b>, which has to be on Simulation. On "
     "anything else the game steers on top of the assist and cancels most "
     "of what it does."),
    ("Drive",
     "Telemetry arrives, the readout comes alive, and the pad reads as "
     "hidden - the game is seeing the assist rather than your controller. "
     "Start the assist before the game: it looks for controllers when it "
     "starts, and a virtual pad made afterwards is invisible to it."),
],
"ru": [
    ("Скачайте и запустите",
     "Один файл, ничего устанавливать не нужно. Возьмите последний релиз и запустите. Windows один раз спросит права администратора — в этот момент ставятся два драйвера."),
    ("Дайте ему настроиться",
     "Оба драйвера лежат внутри exe, так что ничего не качается на вашу машину. Шаги идут сами и показывают, где сейчас находятся. Если Windows просит перезагрузку — её запросил драйвер, и после неё приложение откроется само."),
    ("Запомните, что он просит",
     "Последний шаг установки — единственное, что ассист не может сделать за вас: игре нужно сказать, чтобы она отдавала телеметрию. Значения на экране — Data Out включён, IP 127.0.0.1, порт 20777 — и приложение ждёт здесь, пока данные не пойдут."),
    ("Выставьте в игре",
     "Forza держит это в <b>Settings &rarr; HUD and Gameplay</b>, в самом низу списка, раздел Telemetry. Есть ещё одна важная настройка, и лежит она совсем в другом месте: <b>Settings &rarr; Difficulty &rarr; Steering</b> — она должна стоять на Simulation. При любом другом значении игра подруливает поверх ассиста и гасит большую часть его работы."),
    ("За руль",
     "Телеметрия пошла, показания ожили, а пад числится скрытым — игра видит ассист, а не ваш геймпад. Запускайте ассист до игры: она ищет контроллеры при старте, и виртуальный пад, созданный позже, для неё не существует."),
],
"es": [
    ("Descárgalo y ejecútalo",
     "Un archivo, nada que instalar. Coge la última versión y "
     "ejecútala. Windows pide permisos de administrador una vez: ese "
     "es el momento en que entran los dos controladores."),
    ("Deja que se prepare solo",
     "Los dos controladores van dentro del exe, así que no se descarga "
     "nada en tu equipo. Los pasos se ejecutan solos e indican por "
     "dónde van. Si Windows pide reiniciar, lo ha pedido un "
     "controlador, y la app se abre de nuevo por su cuenta después."),
    ("Apúnta lo que te pide",
     "El último paso de la instalación es lo único que la "
     "asistencia no puede hacer por ti: hay que decirle al juego que "
     "envíe su telemetría. Los valores están en pantalla - "
     "Data Out activado, IP 127.0.0.1, puerto 20777 - y la app espera "
     "aquí hasta que lleguen."),
    ("Configúralo en el juego",
     "Forza lo guarda en <b>Settings &rarr; HUD and Gameplay</b>, al final "
     "de la lista, en Telemetry. Hay otro ajuste que importa y que vive en "
     "un sitio completamente distinto: <b>Settings &rarr; Difficulty "
     "&rarr; Steering</b>, que tiene que estar en Simulation. Con "
     "cualquier otro valor el juego dirige por encima de la asistencia y "
     "anula casi todo lo que hace."),
    ("Conduce",
     "La telemetría llega, la lectura cobra vida y el mando figura "
     "como oculto: el juego está viendo la asistencia y no tu "
     "controlador. Arranca la asistencia antes que el juego: este busca "
     "mandos al iniciarse, y un mando virtual creado después le "
     "resulta invisible."),
],
"fr": [
    ("Téléchargez et lancez",
     "Un fichier, rien à installer. Prenez la dernière version et "
     "lancez-la. Windows demande les droits administrateur une fois : "
     "c'est là que les deux pilotes s'installent."),
    ("Laissez-le se préparer",
     "Les deux pilotes sont dans l'exe, rien n'est téléchargé "
     "sur votre machine. Les étapes se déroulent seules et disent "
     "où elles en sont. Si Windows demande un redémarrage, c'est "
     "un pilote qui l'a demandé, et l'application se rouvre ensuite "
     "d'elle-même."),
    ("Notez ce qu'il demande",
     "La dernière étape est la seule chose que l'assistance ne "
     "peut pas faire à votre place : il faut demander au jeu "
     "d'envoyer sa télémétrie. Les valeurs sont à "
     "l'écran - Data Out activé, IP 127.0.0.1, port 20777 - et "
     "l'application attend ici qu'elles arrivent."),
    ("Réglez-le dans le jeu",
     "Forza range cela dans <b>Settings &rarr; HUD and Gameplay</b>, tout "
     "en bas de la liste, sous Telemetry. Un autre réglage compte, et "
     "il se trouve ailleurs : <b>Settings &rarr; Difficulty &rarr; "
     "Steering</b>, qui doit être sur Simulation. Avec toute autre "
     "valeur, le jeu braque par-dessus l'assistance et annule l'essentiel "
     "de son travail."),
    ("Roulez",
     "La télémétrie arrive, l'affichage s'anime et la "
     "manette est indiquée comme masquée : le jeu voit "
     "l'assistance et non votre manette. Lancez l'assistance avant le "
     "jeu : il cherche les manettes au démarrage, et une manette "
     "virtuelle créée après lui est invisible."),
],
"de": [
    ("Herunterladen und starten",
     "Eine Datei, nichts zu installieren. Nimm die neueste Version und "
     "starte sie. Windows fragt einmal nach Administratorrechten - in dem "
     "Moment kommen die beiden Treiber hinein."),
    ("Lass ihn sich einrichten",
     "Beide Treiber stecken in der exe, es wird nichts auf deinen Rechner "
     "geladen. Die Schritte laufen von selbst und sagen, wo sie stehen. "
     "Verlangt Windows einen Neustart, hat ein Treiber danach gefragt - "
     "danach öffnet sich die App von allein wieder."),
    ("Merk dir, was er verlangt",
     "Der letzte Schritt ist das Einzige, was die Assistenz nicht für "
     "dich erledigen kann: Dem Spiel muss gesagt werden, dass es seine "
     "Telemetrie schickt. Die Werte stehen auf dem Bildschirm - Data Out "
     "an, IP 127.0.0.1, Port 20777 - und die App wartet hier, bis sie "
     "ankommen."),
    ("Im Spiel einstellen",
     "Forza legt das unter <b>Settings &rarr; HUD and Gameplay</b> ab, ganz "
     "unten in der Liste unter Telemetry. Eine weitere Einstellung ist "
     "wichtig und steckt ganz woanders: <b>Settings &rarr; Difficulty "
     "&rarr; Steering</b> muss auf Simulation stehen. Bei allem anderen "
     "lenkt das Spiel über die Assistenz hinweg und hebt das meiste "
     "davon auf."),
    ("Fahr los",
     "Die Telemetrie kommt an, die Anzeige lebt, und der Controller gilt "
     "als versteckt - das Spiel sieht die Assistenz statt deines Pads. "
     "Starte die Assistenz vor dem Spiel: Es sucht beim Start nach "
     "Controllern, und ein danach erzeugtes virtuelles Pad ist für es "
     "unsichtbar."),
],
"ja": [
    ("ダウンロードして起動",
     "ファイルはひとつ、インストール作業はありません。最新リリースを取って実行してください。Windowsが一度だけ管理者権限を求めます。そこで2つのドライバーが入ります。"),
    ("セットアップは任せる",
     "2つのドライバーはexeの中にあり、あなたのPCに何かをダウンロードすることはありません。手順は自動で進み、今どこにいるかを表示します。Windowsが再起動を求めたらドライバーの要求で、再起動後はアプリが自分で立ち上がります。"),
    ("求められる値を控える",
     "セットアップ最後の手順だけは、アシストが代わりにできません。ゲーム側にテレメトリーを送るよう設定する必要があります。値は画面に出ています（Data Out をオン、IP 127.0.0.1、ポート 20777）。データが届くまでアプリはここで待ちます。"),
    ("ゲーム側で設定する",
     "Forzaでは <b>Settings &rarr; HUD and Gameplay</b> の一番下、Telemetry の項目にあります。もうひとつ大事な設定がまったく別の場所にあります。<b>Settings &rarr; Difficulty &rarr; Steering</b> を Simulation にしてください。それ以外だとゲームがアシストの上からステアリングを当て、効果のほとんどを打ち消します。"),
    ("走る",
     "テレメトリーが届いて表示が動き出し、パッドは「隠し済み」と表示されます。ゲームはあなたのコントローラーではなくアシストを見ています。アシストはゲームより先に起動してください。ゲームは起動時にコントローラーを探すので、後から作られた仮想パッドは見えません。"),
],
}

KNOWN = {
"en": [
    ("PlayStation controllers are only half supported",
     "A DualShock or DualSense is read differently from an Xbox pad, and "
     "not everything lands where it should yet."),
    ("The correction pauses while you shift",
     "Press a gear, the camera, or anything else the assist does not carry, "
     "and the game reads your own controller for that moment - steering "
     "included. It is brief, and it is why the wheel can twitch mid-drift. "
     "__SETTING__ removes it on machines where that switch is safe."),
    ("Setup does not go smoothly on every machine",
     "Two drivers, an installer that sometimes wants a restart, and an exe "
     "nobody has signed. Most of what has gone wrong so far happened here."),
    ("Several launches in one sitting can leave it unreliable",
     "Restarting Windows clears it. Most of the causes are fixed; if you "
     "still meet this one, it is worth telling us about."),
],
"ru": [
    ("Геймпады PlayStation поддержаны наполовину",
     "DualShock и DualSense читаются иначе, чем пад Xbox, и пока не всё попадает туда, куда должно."),
    ("Коррекция замолкает, пока вы переключаетесь",
     "Нажали передачу, камеру или что-то ещё, чего ассист не передаёт, — и на этот момент игра читает ваш геймпад напрямую, вместе с рулём. Это доли секунды, и именно из-за них руль может дёрнуться посреди заноса. __SETTING__ убирает это на машинах, где такой переключатель безопасен."),
    ("Установка проходит гладко не на каждой машине",
     "Два драйвера, установщик, который иногда просит перезагрузку, и exe без подписи. Почти всё, что до сих пор ломалось, ломалось именно здесь."),
    ("Несколько запусков подряд могут расшатать работу",
     "Перезагрузка Windows это лечит. Большая часть причин уже устранена; если вы всё же на это наткнулись — расскажите нам."),
],
"es": [
    ("Los mandos de PlayStation solo están soportados a medias",
     "Un DualShock o un DualSense se leen de forma distinta a un mando de "
     "Xbox, y todavía no todo llega donde debería."),
    ("La corrección se pausa mientras cambias de marcha",
     "Pulsa una marcha, la cámara o cualquier otra cosa que la "
     "asistencia no transmite y, en ese instante, el juego lee tu propio "
     "mando, dirección incluida. Dura un momento, y por eso el volante "
     "puede dar un tirón en pleno derrape. __SETTING__ lo elimina en "
     "los equipos donde ese interruptor es seguro."),
    ("La instalación no va bien en todos los equipos",
     "Dos controladores, un instalador que a veces pide reiniciar y un exe "
     "que nadie ha firmado. Casi todo lo que ha salido mal hasta ahora ha "
     "pasado aquí."),
    ("Varios arranques seguidos pueden dejarla inestable",
     "Reiniciar Windows lo soluciona. La mayoría de las causas ya "
     "están corregidas; si aun así te topas con esto, merece la "
     "pena contárnoslo."),
],
"fr": [
    ("Les manettes PlayStation ne sont qu'à moitié prises en "
     "charge",
     "Une DualShock ou une DualSense se lit autrement qu'une manette Xbox, "
     "et tout n'arrive pas encore là où il faudrait."),
    ("La correction se met en pause pendant que vous passez les vitesses",
     "Appuyez sur une vitesse, la caméra ou tout ce que l'assistance "
     "ne transmet pas, et le jeu lit votre manette pendant cet instant, "
     "direction comprise. C'est bref, et c'est pour cela que le volant peut "
     "sursauter en plein drift. __SETTING__ supprime le problème sur "
     "les machines où ce réglage est sans risque."),
    ("L'installation ne se passe pas bien sur toutes les machines",
     "Deux pilotes, un installeur qui réclame parfois un "
     "redémarrage, et un exe que personne n'a signé. L'essentiel "
     "de ce qui a raté jusqu'ici s'est produit là."),
    ("Plusieurs lancements d'affilée peuvent la rendre instable",
     "Redémarrer Windows règle le problème. La plupart des "
     "causes sont corrigées ; si vous tombez encore dessus, "
     "dites-le-nous."),
],
"de": [
    ("PlayStation-Controller werden nur halb unterstützt",
     "Ein DualShock oder DualSense wird anders gelesen als ein Xbox-Pad, "
     "und noch landet nicht alles dort, wo es hingehört."),
    ("Die Korrektur pausiert, während du schaltest",
     "Drückst du einen Gang, die Kamera oder sonst etwas, das die "
     "Assistenz nicht durchreicht, liest das Spiel in diesem Moment deinen "
     "eigenen Controller - die Lenkung eingeschlossen. Es dauert nur einen "
     "Augenblick, und genau deshalb kann das Rad mitten im Drift zucken. "
     "__SETTING__ nimmt das auf Rechnern weg, auf denen dieser Schalter "
     "sicher ist."),
    ("Die Einrichtung läuft nicht auf jedem Rechner glatt",
     "Zwei Treiber, ein Installer, der manchmal einen Neustart will, und "
     "eine exe, die niemand signiert hat. Das meiste, was bisher schiefging, "
     "ging hier schief."),
    ("Mehrere Starts hintereinander können sie unzuverlässig "
     "machen",
     "Ein Neustart von Windows räumt das auf. Die meisten Ursachen "
     "sind behoben; falls es dir trotzdem begegnet, sag uns Bescheid."),
],
"ja": [
    ("PlayStationのコントローラーは対応が半分",
     "DualShockやDualSenseはXboxパッドとは読み取り方が違い、まだすべてが正しい場所に届いていません。"),
    ("シフト操作の間、補正が止まる",
     "ギアやカメラなど、アシストが中継していないボタンを押すと、その瞬間だけゲームはあなたのコントローラーを直接読みます。ステアリングも含めてです。ごく短い時間ですが、ドリフト中にハンドルが跳ねるのはこれが原因です。__SETTING__ を使える環境なら、これをなくせます。"),
    ("すべての環境でセットアップがすんなり進むわけではない",
     "ドライバーが2つ、ときどき再起動を求めるインストーラー、そして署名のないexe。これまでに起きた不具合のほとんどはここで起きています。"),
    ("同じセッションで何度も起動すると不安定になることがある",
     "Windowsを再起動すれば直ります。原因の多くはすでに修正済みですが、それでも起きた場合はぜひ知らせてください。"),
],
}

ROADMAP = {
"en": [
    ("Presets that follow the car",
     "The telemetry already names what you are driving."),
    ("An oversteer assist",
     "Catching the car before it is sideways, not only after."),
    ("Drift angle and stability, as dials",
     "The numbers exist; they are just shown as numbers."),
    ("Statistics, on a screen of their own",
     "Time sideways, longest drift, how often it saved you."),
    ("PlayStation controllers, properly",
     "Needs a pad in hand - guessing from documentation is how the "
     "language bugs happened."),
    ("Keys for the settings you change most",
     "Strength up and down without leaving the car."),
    ("An overlay, inside the game",
     "Everything above, without alt-tabbing to see it."),
],
"ru": [
    ("Пресеты, привязанные к машине",
     "Телеметрия и так называет, на чём вы едете."),
    ("Ассистент против избыточной поворачиваемости",
     "Ловить машину до того, как её развернуло, а не только после."),
    ("Угол и стабильность дрифта — приборами",
     "Цифры уже есть, просто показаны цифрами."),
    ("Статистика на отдельной вкладке",
     "Время в заносе, самый длинный дрифт, сколько раз вас спасли."),
    ("Геймпады PlayStation — по-настоящему",
     "Нужен пад в руках: догадки по документации уже однажды привели к багам с языками."),
    ("Горячие клавиши для частых настроек",
     "Прибавить или убавить силу, не выходя из машины."),
    ("Оверлей прямо в игре",
     "Всё перечисленное — без сворачивания игры."),
],
"es": [
    ("Ajustes que siguen al coche",
     "La telemetría ya dice qué estás conduciendo."),
    ("Un asistente contra el sobreviraje",
     "Atrapar el coche antes de que se cruce, no solo después."),
    ("Ángulo y estabilidad del derrape, como relojes",
     "Los números ya existen; solo que se muestran como números."),
    ("Estadísticas en su propia pantalla",
     "Tiempo de través, el derrape más largo, cuántas veces "
     "te ha salvado."),
    ("Mandos de PlayStation, en condiciones",
     "Hace falta tener uno en la mano: adivinar a partir de la "
     "documentación es justo lo que provocó los fallos con los "
     "idiomas."),
    ("Teclas para los ajustes que más cambias",
     "Subir y bajar la fuerza sin salir del coche."),
    ("Una superposición dentro del juego",
     "Todo lo anterior, sin salir del juego para verlo."),
],
"fr": [
    ("Des préréglages qui suivent la voiture",
     "La télémétrie donne déjà le nom de ce que "
     "vous conduisez."),
    ("Une aide contre le survirage",
     "Rattraper la voiture avant qu'elle ne se mette en travers, pas "
     "seulement après."),
    ("Angle et stabilité du drift, en cadrans",
     "Les chiffres existent déjà ; ils sont simplement "
     "affichés comme des chiffres."),
    ("Des statistiques, sur leur propre écran",
     "Temps en travers, plus long drift, nombre de fois où il vous a "
     "sauvé."),
    ("Les manettes PlayStation, correctement",
     "Il faut en avoir une en main : deviner d'après la documentation, "
     "c'est ainsi que sont nés les bugs de langue."),
    ("Des raccourcis pour les réglages que vous changez le plus",
     "Monter ou baisser la force sans quitter la voiture."),
    ("Une surcouche dans le jeu",
     "Tout ce qui précède, sans alt-tab pour le voir."),
],
"de": [
    ("Presets, die zum Auto gehören",
     "Die Telemetrie nennt ohnehin, was du fährst."),
    ("Eine Hilfe gegen Übersteuern",
     "Das Auto fangen, bevor es quer steht, nicht erst danach."),
    ("Driftwinkel und Stabilität als Anzeigen",
     "Die Zahlen gibt es längst, sie stehen nur als Zahlen da."),
    ("Statistiken auf einem eigenen Bildschirm",
     "Zeit quer, längster Drift, wie oft er dich gerettet hat."),
    ("PlayStation-Controller, richtig",
     "Dafür braucht es ein Pad in der Hand - aus der Dokumentation zu "
     "raten hat schon die Sprachfehler verursacht."),
    ("Tasten für die Einstellungen, die du am häufigsten "
     "änderst",
     "Stärke rauf und runter, ohne aus dem Auto zu steigen."),
    ("Ein Overlay im Spiel",
     "Alles davon, ohne zum Ansehen aus dem Spiel zu wechseln."),
],
"ja": [
    ("車ごとのプリセット",
     "テレメトリーは今も、乗っている車の名前を送っています。"),
    ("オーバーステア対策のアシスト",
     "横を向いてからではなく、その前に止める。"),
    ("ドリフト角と安定度をメーターで",
     "数値はすでにあります。ただ数値のまま出しているだけです。"),
    ("統計を専用の画面で",
     "横を向いていた時間、最長ドリフト、助けられた回数。"),
    ("PlayStationのコントローラーに本気で対応",
     "実機が要ります。資料からの推測で進めた結果が、あの言語まわりの不具合でした。"),
    ("よく変える設定にキー割り当て",
     "車から降りずに効きを上げ下げ。"),
    ("ゲーム内オーバーレイ",
     "ここまでの機能を、Alt+Tabせずに見られるように。"),
],
}


def _check():
    """No language may be short an entry, and none may carry a spare.

    A page is built from the English tables and swapped in the browser by
    key, so a missing entry does not fail loudly - it leaves one line in
    English among five that changed. This is the only place that catches
    that.
    """
    for name, table in (("UI", UI), ("FEATURES", FEATURES),
                        ("STEPS", STEPS), ("KNOWN", KNOWN),
                        ("ROADMAP", ROADMAP)):
        assert set(table) == set(LANGS), "%s: %s" % (name, sorted(table))
        base = table["en"]
        for lang in LANGS:
            got = table[lang]
            assert len(got) == len(base), (
                "%s/%s: %d entries, English has %d"
                % (name, lang, len(got), len(base)))
            if name == "UI":
                assert set(got) == set(base), (
                    "%s/%s: %s" % (name, lang,
                                   set(base).symmetric_difference(got)))
            else:
                for i, pair in enumerate(got):
                    assert len(pair) == 2, "%s/%s/%d" % (name, lang, i)
        if name == "UI":
            for lang in LANGS:
                assert "__VER__" in table[lang]["ver"], lang
        if name == "KNOWN":
            for lang in LANGS:
                assert "__SETTING__" in table[lang][1][1], lang


_check()
