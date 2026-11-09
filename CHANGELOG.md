# Changelog / Список изменений

## 1.4.2

**English**

- **A guide on the Filter page.** Each step has a "?" that opens what it does in plain words, with examples: which usual filter to pick and how it is joined, what the lines, thresholds, loudness and ⚙ mean, kinds and single goods, hiding the cheap, and how to turn the filter on in the game.

**Русский**

- **Гайд на странице «Фильтр».** У каждого шага есть «?»: там простыми словами и с примерами, что он делает — какой обычный фильтр выбрать и как он подключается, что значат строки, пороги, громкость и ⚙, виды и отдельные предметы, скрытие дешёвого и как включить фильтр в игре.

## 1.4.0

**English**

- **Loot filter by price.** A new Filter page builds `Sakuya.filter` in the game's filter folder from current prices, in six steps:
  1. your usual filter, added underneath as a copy (works for sure) or as an Import line;
  2. one to six lines by worth, each with its own name, threshold, colour and how loud it is: loud, an icon, colour only, or your own font size, beam, minimap icon, sound and volume. Sounds can be the game's, a ready pack (chimes, soft, coins) or your own mp3 or wav, with a ▶ to listen. Presets from soft to strict set it all at once;
  3. whole kinds of goods softer, stricter or left alone;
  4. single goods always loud, always hidden, or as in your usual filter;
  5. hiding what is cheap (Exalted, Chaos and Divine are never hidden);
  6. saving to the game, with the file following the prices by itself if you like.
  A preview shows how the lines look in the game. Sakuya reads nothing of the game: pick Sakuya in the game's filter options, and press Reload there to see a newer file.
- **Faster first start.** Mods from poe2db come three pages at a time: about a minute and a half instead of five, jewel mods in seconds.

**Русский**

- **Фильтр по ценам.** Новая страница «Фильтр» собирает `Sakuya.filter` в папке фильтров игры из текущих цен, за шесть шагов:
  1. ваш обычный фильтр снизу, копией (работает наверняка) или строкой Import;
  2. от одной до шести строк по стоимости, у каждой своё название, порог, цвет и громкость: громко, значок, только цвет или свои размер шрифта, луч, значок на миникарте, звук и громкость. Звук из игры, готовый набор (колокольчики, мягкие, монеты) или свой mp3 или wav, с кнопкой ▶ послушать. Наборы от мягкого до строгого ставят всё сразу;
  3. целые виды товаров мягче, строже или как есть;
  4. отдельные товары всегда громко, всегда скрыть или как в обычном фильтре;
  5. скрытие дешёвого (Exalted, Chaos и Divine не прячутся никогда);
  6. сохранение в игру, а при желании файл сам обновляется по ценам.
  Предпросмотр показывает, как строки будут выглядеть в игре. Sakuya ничего не читает из игры: выберите Sakuya в настройках фильтра в игре, а чтобы игра увидела новый файл, перезагрузите фильтр там же.
- **Первый запуск быстрее.** Моды с poe2db качаются по три страницы сразу: около полутора минут вместо пяти, моды самоцветов за секунды.

## 1.3.1

**English**

- **Open with the game.** Settings, Window, "Open with Path of Exile 2": a small watcher with no window starts with Windows and opens Sakuya when the game starts, once per start; if Sakuya is already open, it leaves it be. It only sees which programs are running, as Task Manager shows them, and reads nothing of the game. Turn the switch off and the watcher removes itself.

**Русский**

- **Открывать вместе с игрой.** Настройки, «Окно», «Открывать вместе с Path of Exile 2»: маленький сторож без окна запускается с Windows и открывает Sakuya, когда запускается игра, один раз на каждый запуск; если Sakuya уже открыта, не трогает её. Он видит только список запущенных программ, как в диспетчере задач, и ничего не читает из игры. Выключите тумблер, и сторож уберёт себя сам.

## 1.3.0

**English**

- **Two new themes.** "Gold": black lacquer and gold leaf, with the program's name in gold. "Murasaki": a deep violet night. Pick them in Settings, Appearance.
- **Gold is the first theme for new players.** If you already use Sakuya, your theme stays as it was.
- The GitHub page has a new demo and screenshots, with the build page, the search for your level, similar jewels and where uniques drop.

**Русский**

- **Две новые темы.** «Золото»: чёрный лак и золото, название программы тоже золотое. «Мурасаки»: глубокая фиолетовая ночь. Выбираются в Настройках, раздел «Оформление».
- **«Золото» — первая тема для новых пользователей.** Если вы уже пользуетесь Sakuya, ваша тема останется прежней.
- На странице GitHub новое видео и скриншоты: «Билд», поиск под ваш уровень, похожие самоцветы и где падают уники.

## 1.2.8

**English**

- **Find a similar jewel.** On the build page, a jewel shows its mods in your language with their range on that kind of jewel, such as "13% increased Chaos Damage (7–13)". All are ticked at first; click to untick. "Mod's range" searches each mod from the low end of its range, "As on the item" from the jewel's own values. The trade site opens with jewels of the same kind that have every ticked mod. Jewel mods come from poe2db, once a week and after a patch.
- **For your level, simpler.** Picking a level ticks every mod of the item that level can have, at the values of the tier that level has; untick what you do not need. Every ticked mod is required. The strictness list is gone.
- Mods the level cannot have show crossed out, with the level they come at; mods the trade site has no filter for show greyed and are left out of the search.
- **Fixed:** a mod the trade site lists twice, as a local and a global stat (flat energy shield, armour, evasion, accuracy, spirit, rarity and others), was searched by one of them only, so a similar item could be missed. It now asks for either, as the price window does.
- **Fixed:** a hybrid mod's two lines could be asked as "2 of 3", letting an item without one of them through. Every line is required now.
- **Fixed:** an item whose Path of Building code has no level requirement got no "For your level" block. The requirement is now estimated from its strongest mod, shown as "needs about level N".
- **Wiki links.** Every currency card opens its item on poe2wiki, and every hot item has a card with a Wiki button; a unique's name there is a link too.

**Русский**

- **Похожий самоцвет.** В «Билде» у самоцвета видны его моды по-русски с разбросом на этом виде самоцвета, например «13% увеличение урона хаосом (7–13)». Сразу отмечены все, клик снимает. «Диапазон мода» ищет каждый мод от нижней границы разброса, «Как на предмете» — от значений на самоцвете. Сайт торговли открывается с самоцветами того же вида, у которых есть все отмеченные моды. Моды самоцветов берутся с poe2db раз в неделю и после патча.
- **«Под твой уровень» проще.** При выборе уровня отмечены все моды вещи, что бывают на этом уровне, со значениями тира этого уровня; лишние снимите. Все отмеченные моды обязательны. Список строгости убран.
- Моды, которых на уровне не бывает, показаны зачёркнутыми, с уровнем, с которого появятся; моды, для которых у сайта торговли нет фильтра, — серым, в поиск не идут.
- **Исправлено:** мод, который сайт торговли знает в двух видах, локальном и глобальном (плоский энергощит, броня, уклонение, точность, дух, редкость и другие), искался только по одному из них, и похожая вещь могла не найтись. Теперь ищется любой из двух, как в окне цены.
- **Исправлено:** две строки гибридного мода могли искаться как «2 из 3», и подходила вещь без одной из них. Теперь обязательна каждая строка.
- **Исправлено:** у вещи, в коде Path of Building которой нет требования уровня, не было блока «Под твой уровень». Теперь требование оценивается по самому сильному моду и показано как «требует ~N ур.».
- **Ссылки на вики.** Любая карточка «Валюты» открывает предмет на poe2wiki, у каждой строки «Ходового» есть карточка с кнопкой «Вики», а название уника в ней — ссылка.

## 1.2.7

**English**

- **Clearer item frames on the build page.** Every item has a plain grey frame, and the one you picked is outlined in the program's pink, so it is easy to see which item the panel on the right shows. The rarity shows in the item's name there.

**Русский**

- **Понятнее рамки вещей в «Билде».** У всех вещей простая серая рамка, а выбранная обведена розовым цветом программы, поэтому сразу видно, какую вещь показывает панель справа. Редкость видна по цвету названия в этой панели.

## 1.2.6

**English**

- **Updates show within ten minutes.** The program looks for a newer version as soon as it starts and then every ten minutes, instead of once in six hours with the data. The update tag above the window appears at once; nothing is downloaded until you press "Update to …". Offline, it waits quietly.

**Русский**

- **Обновления видны за 10 минут.** Программа ищет новую версию сразу при запуске и потом каждые 10 минут, а не раз в 6 часов вместе с базами. Плашка над окном появляется сразу; ничего не скачивается, пока вы не нажмёте «Обновить до…». Без интернета проверка ждёт молча.

## 1.2.5

**English**

- **For your level.** On the build page, type your level in "My level"; it applies as you type and is remembered. An item you cannot wear yet shows "Needs level 50, you are 30" and a path of levels toward it, such as You 30 ► 33 ► 37 ► 44 ► 48 ► 50: each step is a level where a better tier of one of its main mods opens. Pick a step to see what opens there, tick which mods to search for (they light up pink, as on the trade site), and read what will be searched before you open it.
- **A similar item on the trade site.** One button opens the trade site with any base of that kind (or only this base), a level requirement band around the picked level (for 37: 36–43) and the ticked mods at the values that level allows. Four ways to choose the mods: the key mod, loose, normal and strict. Loot mods such as rarity come last. The program still only opens a link: you search there yourself.
- **Craft for a level.** "Craft for level N" opens the planner with the item's main mods at the best tiers that level allows, and an item level that keeps the result wearable.
- **Items copied in the game.** Paste an item copied with `Ctrl+Alt+C` into the build page, and it opens on its own with its level and the same tools.
- **Build history.** Every opened code is kept, newest first, as "Name · class · ascendancy · level". The character name comes from a poe.ninja export; for a code with none, type a name and it is kept. Up to 30 builds, stored next to the program only.
- Item details show the level an item needs beside its item level, and each mod shows what your level allows of it.
- The details panel scrolls, and keeps its place when you pick a mod or a level.
- **Fixed:** with a Russian keyboard layout Ctrl+V, C, X and A did nothing in text fields, and Ctrl+Backspace removed one letter. They work in any layout now.

**Русский**

- **Под твой уровень.** В разделе «Билд» впишите свой уровень в «Мой уровень»: он применяется сразу, без кнопки, и запоминается. У вещи, которую ещё не надеть, видно «Нужен 50 ур., у тебя 30» и путь уровней к ней, например Ты 30 ► 33 ► 37 ► 44 ► 48 ► 50: каждая ступень — уровень, где открывается тир получше у одного из главных модов. Выберите ступень, посмотрите, что на ней открывается, отметьте моды для поиска (они подсвечиваются розовым, как на сайте торговли) и прочитайте, что будет искаться, до того как открыть.
- **Похожая вещь на трейде.** Одна кнопка открывает сайт торговли: любая база этого вида (или только эта), требование уровня в полосе вокруг выбранного (для 37 — 36–43) и отмеченные моды со значениями, которые бывают на этом уровне. Четыре способа выбрать моды: главный мод, мягко, средне и строго. Моды добычи вроде редкости идут последними. Программа по-прежнему только открывает ссылку: ищете вы сами.
- **Скрафтить на уровень.** «Скрафтить на N ур.» открывает крафт с главными модами вещи в лучших тирах, доступных на этом уровне, и уровнем предмета, при котором вещь можно надеть.
- **Предметы из игры.** Вставьте в «Билд» предмет, скопированный через `Ctrl+Alt+C`, и он откроется сам, со своим уровнем и теми же кнопками.
- **История билдов.** Каждый открытый код сохраняется, новые сверху, как «Имя · класс · восхождение · уровень». Имя персонажа берётся из экспорта poe.ninja; если в коде его нет, впишите ник, и он сохранится. До 30 билдов, только в файле рядом с программой.
- В деталях вещи видно, с какого уровня её можно надеть, а у каждого мода — что из него доступно на вашем уровне.
- Панель деталей прокручивается и не прыгает наверх, когда выбираете мод или уровень.
- **Исправлено:** при русской раскладке Ctrl+V, C, X и A не работали в полях ввода, а Ctrl+Backspace стирал по одной букве. Теперь работают в любой раскладке.

## 1.2.0

**English**

- **Build page.** Paste a Path of Building code (from Path of Building, a guide, or the export on a poe.ninja character) and see the build's gear laid out as in the game, with the jewels from its passive tree. Every mod gets its side and tier from the program's mod lists; click an item for its price window, trade link and "Improve in the planner". The code is read on your computer: nothing is fetched, and links are not followed.
- **Where it drops.** A new page lists every unique and jewel base with where it comes from: the Simulacrum, a boss, Atziri's Vault, a Trial cache, crafting, or anywhere from a zone level. Filters, search in both languages, a click opens the item on the wiki. Where players have measured it, the chance is shown as runs on average, with its rate and the game version of the sample beneath, for example Voices at about 1 in 100 Simulacrums (~1%, 0.5.0); for other uniques, how many are on the market. The build page shows it for each unique too. Data from poe2wiki.net, read once a week and right after the update.
- **Precursor Tablets** have their own price tab, with plain, magic and rare tablets priced apart; the price check finds a copied tablet by its rarity.
- **Uniques in hardcore and Standard.** Where poe2scout has no uniques, hot items and the price check take them from poe.ninja.
- Jewel, flask and charm bases are shown by their Russian names, from poe2db, and the price window shows their pictures.
- The league list now comes from poe.ninja's public economy API, as its rules for programs ask.

**Русский**

- **Раздел «Билд».** Вставьте код Path of Building (из самого PoB, гайда или кнопки экспорта у персонажа на poe.ninja), и снаряжение билда встанет так же, как в игре, вместе с самоцветами из дерева. У каждого мода видны сторона и тир из списков модов программы; клик по предмету открывает окно цены, ссылку на трейд и «Улучшить в крафте». Код читается на вашем компьютере: ничего не скачивается, по ссылкам программа не ходит.
- **Где падает.** Новая страница: все уники и базы самоцветов и откуда они берутся — Симулякр, босс, Хранилище Атзири, сундук испытания, создание или где угодно с уровня зоны. Фильтры, поиск на двух языках, клик открывает предмет на вики. Где игроки это замеряли, шанс показан числом попыток в среднем, а под ним процент и версия игры, на которой считали: например, «Голоса» — примерно 1 из 100 Симулякров (~1%, 0.5.0); у остальных уников — сколько их на рынке. В разделе «Билд» это видно и у каждого уника. Данные poe2wiki.net, раз в неделю и сразу после обновления.
- **Скрижали предтеч** на своей вкладке цен, обычные, магические и редкие отдельно; проверка цены находит скопированную скрижаль по её редкости.
- **Уники в хардкоре и Standard.** Где у poe2scout уников нет, «Ходовое» и проверка цены берут их с poe.ninja.
- Базы самоцветов, флаконов и оберегов показаны русскими названиями с poe2db, а окно цены показывает их картинки.
- Список лиг берётся из открытого экономического API poe.ninja, как просят его правила для программ.

## 1.1.0

**English**

- **Presets.** A small window beside the main one lists ready goals that fit the open base: energy shield, evasion, armour and their hybrids, life and resistances, movement speed, spirit, block, weapons, spells, minions, rings, amulets, quivers. One click marks the mods and works out the path. Your own goals are saved with "Save goal".
- **Base search as you type.** The base field shows matching bases while you type, in Russian or English, grouped by kind (body armour, boots, rings and so on).
- **Catalysts in the planner.** A ring or amulet can be filled with catalyst quality and crafted under the Omen of Catalysing Exaltation; the plan takes it when it pays. A Breach Ring takes 40% quality, a Refined Breach Ring 45%.
- **Lich omens.** The Omen of the Sovereign, the Liege and the Blackblooded make a bone offer a mod of Ulaman, Amanamu or Kurgal; the plan uses them for a wanted mod of that lich on weapons and jewellery.
- **Fixed: rings and amulets with other room for mods.** Dusk, Gloam, Penumbra and Tenebrous rings and amulets, and the Twisted, Lament, Distorted, Portent and Absent amulets take more or fewer than 3 prefixes or suffixes. The planner counted 3 and 3 on all of them; it now follows the base.
- After crafting, the Essence of the Breach hint now shows for amulets too, with the real quality cap of the base.
- **Any N of a group.** Mark mods with "◇ any of the group" and choose how many of them are needed, for example any 2 of 3 resistances. Such goals are much cheaper than asking for all of them.
- **Keep a place free.** A switch above the prefixes and the suffixes keeps one place empty, for a mod you will add later.
- **Goal codes.** "Goal code" copies the goal as one line to send to a friend; "Paste code" opens it, with the base, mods, tiers, group and free places.
- **Two clearer modes.** "Cheapest" is the least spent on average. "Fewer steps" takes fewer, better orbs: each step weighs as much as an average step of the cheapest plan, so it makes sense for a cheap ring and for a mirror item alike. The old budget mode skipped every step above 0.2 Divine and could make absurd plans.
- Back from a plan to the mods, the chosen mods stay chosen.
- Fixed: plans that fracture a mod and then start on a new base showed far too low a cost.
- Fixed: clicking several presets in a row started a plan for each, and large goals could bring the program down. One plan is worked out at a time, and the presets wait for it; a plan of a base you have left stops at once.
- Plans are worked out about twice as fast, with less memory.
- Fixed: the program slowly used more memory with every item checked and every change of language or theme.
- Fixed: the preset window could stay behind after the main window was moved, and the base list could stay open over another tab.

**Русский**

- **Пресеты.** Рядом с основным окном небольшое окно с готовыми целями для открытой базы: энергощит, уклонение, броня и гибриды, здоровье и сопротивления, скорость передвижения, дух, блок, оружие, чары, миньоны, кольца, амулеты, колчаны. Один клик отмечает моды и сразу считает путь. Свои цели сохраняются кнопкой «Сохранить цель».
- **Поиск базы по ходу ввода.** Под полем «База» появляются подходящие базы, по-русски или по-английски, разбитые по видам (нательная броня, сапоги, кольца и т. д.).
- **Катализаторы в планировщике.** Кольцо или амулет можно заточить катализаторами и крафтить со знамением Catalysing Exaltation; план берёт это, когда выгодно. Кольцо разлома держит 40% качества, очищенное кольцо разлома 45%.
- **Знамения личей.** Omen of the Sovereign, the Liege и the Blackblooded заставляют кость предложить мод Уламана, Аманаму или Кургала; план использует их для нужного мода этого лича на оружии и бижутерии.
- **Исправлено: кольца и амулеты с другим числом модов.** Кольца и амулеты Dusk, Gloam, Penumbra и Tenebrous, амулеты Twisted, Lament, Distorted, Portent и Absent держат больше или меньше 3 префиксов или суффиксов. Планировщик считал 3 и 3 на всех, теперь учитывает базу.
- Подсказка про Essence of the Breach после крафта теперь есть и для амулетов, с настоящим потолком качества базы.
- **Любые N из группы.** Отметьте моды меткой «◇ любой из группы» и выберите, сколько из них нужно, например любые 2 из 3 сопротивлений. Такие цели намного дешевле, чем все моды сразу.
- **Оставить место.** Переключатель над префиксами и суффиксами оставляет одно место пустым под мод, который вы добавите потом.
- **Код цели.** «Код цели» копирует цель одной строкой, чтобы отправить другу; «Вставить код» открывает её с базой, модами, тирами, группой и свободными местами.
- **Два понятных режима.** «Дешевле всего» — меньше всего трат в среднем. «Меньше действий» — меньше шагов лучшими сферами: каждый шаг весит столько, сколько в среднем стоит шаг самого дешёвого плана, поэтому режим разумен и для дешёвого кольца, и для мирор-вещи. Старый режим «За копейки» пропускал все шаги дороже 0,2 Divine и мог выдавать абсурдные планы.
- После возврата из плана к модам выбранные моды остаются выбранными.
- Исправлено: планы, которые раскалывают мод и потом берут новую базу, показывали сильно заниженную цену.
- Исправлено: несколько кликов по пресетам подряд запускали расчёт на каждый, и на больших целях программа могла упасть. Теперь план считается один, пресеты ждут его, а расчёт для базы, с которой вы ушли, сразу останавливается.
- Планы считаются примерно вдвое быстрее и занимают меньше памяти.
- Исправлено: программа понемногу занимала всё больше памяти с каждой проверкой предмета и каждой сменой языка или темы.
- Исправлено: окно пресетов могло отстать от основного окна после его перемещения, а список баз — остаться открытым поверх другой вкладки.

On the first start the crafting data downloads again in the background, a few minutes, as mods now carry the tags catalysts work with. / При первом запуске данные для крафта скачаются заново в фоне, это несколько минут: у модов теперь есть метки, с которыми работают катализаторы.

## 1.0.1

**English**

- **One-click update.** When a new version is out, a tag above the window says so: click it, or use the Divine page or the tray menu. The new file is downloaded next to the program, checked against the checksum GitHub publishes for it, and put in place, and Sakuya restarts in the new version. If anything goes wrong, the old version stays and the release page opens. Nothing is downloaded until you click.
- **Report a problem.** A button on the Divine page and in the tray menu opens a new issue on GitHub, with a ready form for a wrong crafting plan.
- **Sakuya on GitHub.** A button on the Divine page and in the tray menu.
- The Divine page fits better on small screens.

**Русский**

- **Обновление одной кнопкой.** Когда выходит новая версия, над окном появляется плашка: нажмите на неё, или на кнопку в разделе «Divine», или на пункт в меню трея. Новый файл скачивается рядом с программой, сверяется с контрольной суммой, которую публикует GitHub, и встаёт на место старого, а Sakuya перезапускается уже новой версией. Если что-то пошло не так, остаётся старая версия и открывается страница релиза. Без нажатия ничего не скачивается.
- **Сообщить о проблеме.** Кнопка в разделе «Divine» и пункт в меню трея открывают новый Issue на GitHub с готовой формой для неправильного плана крафта.
- **Sakuya на GitHub.** Кнопка в разделе «Divine» и пункт в меню трея.
- Раздел «Divine» лучше помещается на маленьких экранах.

Version 1.0.0 shows a new version only as a line in the status bar: download 1.0.1 from Releases once by hand, and later updates take one click. / Версия 1.0.0 сообщает о новой версии только строкой внизу окна: один раз скачайте 1.0.1 из Releases вручную, дальше обновления ставятся одной кнопкой.

## 1.0.0

The first release: crafting planner, price checks, market lists, tools, price watches, history, league choice, three themes. / Первый релиз: планировщик крафта, проверка цен, списки рынка, инструменты, слежение за ценой, история, выбор лиги, три темы.
