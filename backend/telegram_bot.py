<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Acwellan</title>
    <link rel="stylesheet" href="style.css?v=3">
</head>
<body>
    <header class="header">
        <div class="logo">Acwellan</div>
        <nav class="nav">
            <button type="button" class="nav-btn active" data-tab="matches">Матчи</button>
            <button type="button" class="nav-btn" data-tab="history">История</button>
        </nav>
    </header>

    <main class="container">
        <section id="tab-matches" class="tab-content active">
            <div class="filters">
                <select id="league-filter">
                    <option value="all">Все лиги</option>
                    <option value="EPL">Англия</option>
                    <option value="LaLiga">Испания</option>
                    <option value="Bundesliga">Германия</option>
                    <option value="SerieA">Италия</option>
                    <option value="Ligue1">Франция</option>
                </select>
                <input type="date" id="date-filter">
            </div>
            <div class="matches-list"></div>
        </section>

        <section id="tab-history" class="tab-content">
            <div class="predictions-header">
                <h2>История прогнозов</h2>
                <p class="subtitle">Результаты прошлых ставок</p>
            </div>
            <div class="history-list"></div>
        </section>
    </main>

    <!-- ?v=3 — обход кэша -->
    <script src="script.js?v=3"></script>
</body>
</html>