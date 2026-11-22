/**
 * CINEPASS PLATFORM — CLIENT APPLICATION
 * High-performance, modular ES6+ reactive frontend.
 */

(() => {
  "use strict";

  // --- Global Application State ---
  const state = {
    user: null,
    selectedCity: localStorage.getItem("cinepass_city") || "Mumbai",
    homepageData: null,
    movies: new Map(),
    cinemas: new Map(),
    activeHeroIndex: 0,
    heroTimer: null,
    booking: {
      show: null,
      selectedDate: null,
      selectedSeats: new Set(),
      lockedSeatIds: [],
      lockTimerInterval: null,
      lockExpiresAt: null,
      snacks: new Map(), // snack_id -> { item, quantity }
      couponCode: null,
      couponDiscount: 0,
      breakdown: null,
      orderData: null,
    },
    watchlist: new Set(),
  };

  const byId = (id) => document.getElementById(id);
  const qAll = (selector, parent = document) => [...parent.querySelectorAll(selector)];

  const escapeHtml = (val) =>
    String(val ?? "").replace(/[&<>'"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;" }[c]));

  const formatCurrency = (amt) =>
    `₹${Number(amt || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  async function api(endpoint, options = {}) {
    const defaultHeaders = { "Content-Type": "application/json" };
    const token = localStorage.getItem("cinepass_token");
    if (token) {
      defaultHeaders["Authorization"] = `Bearer ${token}`;
    }
    const sessionToken = localStorage.getItem("cinepass_session_id") || "sess_" + Math.random().toString(36).substring(2);
    localStorage.setItem("cinepass_session_id", sessionToken);
    defaultHeaders["X-Session-ID"] = sessionToken;

    const res = await fetch(endpoint, {
      ...options,
      headers: { ...defaultHeaders, ...(options.headers || {}) },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.message || `API error (${res.status})`);
    }
    return data;
  }

  // --- Modal Utilities ---
  function openModal(id) {
    const el = byId(id);
    if (el) {
      el.hidden = false;
      document.body.style.overflow = "hidden";
    }
  }

  function stopTrailer() {
    const wrap = byId("trailer-iframe-wrap");
    if (wrap) {
      const iframe = wrap.querySelector("iframe");
      if (iframe) {
        iframe.src = "";
      }
      wrap.innerHTML = "";
    }
  }

  function closeModal(id) {
    const el = byId(id);
    if (el) {
      if (id === "trailer-modal" || el.querySelector("#trailer-iframe-wrap")) {
        stopTrailer();
      }
      el.hidden = true;
      if (!document.querySelector(".modal-overlay:not([hidden])")) {
        document.body.style.overflow = "";
      }
    }
  }

  // Close modals on data-close-modal click or ESC key
  document.addEventListener("click", (e) => {
    const closeBtn = e.target.closest("[data-close-modal]");
    if (closeBtn) {
      const modalId = closeBtn.dataset.closeModal;
      closeModal(modalId);
    } else if (e.target.classList.contains("modal-overlay")) {
      closeModal(e.target.id);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      stopTrailer();
      qAll(".modal-overlay:not([hidden])").forEach((m) => {
        closeModal(m.id);
      });
      byId("search-autocomplete-dropdown").hidden = true;
      byId("user-dropdown-panel").hidden = true;
    }
    // Ctrl+K shortcut for search
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      byId("global-search-input").focus();
    }
  });

  // --- City Selector ---
  async function loadCities() {
    try {
      const data = await api("/api/cinemas/cities");
      const list = byId("popular-cities-list");
      list.innerHTML = "";
      data.cities.forEach((c) => {
        const pill = document.createElement("button");
        pill.className = `city-select-pill ${c.name.toLowerCase() === state.selectedCity.toLowerCase() ? "active" : ""}`;
        pill.textContent = c.name;
        pill.onclick = () => selectCity(c.name);
        list.appendChild(pill);
      });
    } catch (e) {
      console.warn("Could not load cities:", e);
    }
  }

  function selectCity(cityName) {
    state.selectedCity = cityName;
    localStorage.setItem("cinepass_city", cityName);
    byId("current-city-label").textContent = cityName;
    byId("cinema-city-heading").textContent = cityName;
    closeModal("city-modal");
    loadCinemas();
    if (state.booking.show) {
      loadShowtimesForMovie(state.booking.show.movie_id || state.booking.show.movie?.id);
    }
  }

  // --- Authentication Management ---
  async function checkAuth() {
    try {
      const data = await api("/api/auth/me");
      if (data.user) {
        setLoggedIn(data.user);
      } else {
        setLoggedOut();
      }
    } catch {
      setLoggedOut();
    }
  }

  function setLoggedIn(user) {
    state.user = user;
    byId("auth-actions-wrap").hidden = true;
    byId("user-profile-menu-wrap").hidden = false;
    byId("user-display-name").textContent = user.name.split(" ")[0];
    byId("user-avatar-initial").textContent = user.name.charAt(0).toUpperCase();
    byId("dropdown-user-name").textContent = user.name;
    byId("dropdown-user-email").textContent = user.email;

    // Show admin options if user is admin
    const adminItems = qAll(".admin-only-item");
    adminItems.forEach((el) => (el.hidden = user.role !== "admin"));

    loadUserWatchlist();
  }

  function setLoggedOut() {
    state.user = null;
    localStorage.removeItem("cinepass_token");
    byId("auth-actions-wrap").hidden = false;
    byId("user-profile-menu-wrap").hidden = true;
    byId("user-dropdown-panel").hidden = true;
    state.watchlist.clear();
  }

  async function loadUserWatchlist() {
    if (!state.user) return;
    try {
      const data = await api("/api/auth/watchlist");
      state.watchlist = new Set((data.watchlist || []).map((m) => m.id));
      updateWatchlistButtons();
    } catch (e) {
      console.warn("Watchlist error:", e);
    }
  }

  function updateWatchlistButtons() {
    qAll("[data-movie-watchlist-id]").forEach((btn) => {
      const mid = btn.dataset.movieWatchlistId;
      btn.classList.toggle("active", state.watchlist.has(mid));
    });
  }

  async function toggleWatchlist(movieId, btnElement) {
    if (!state.user) {
      openModal("auth-modal");
      return;
    }
    try {
      const res = await api(`/api/auth/watchlist/${movieId}`, { method: "POST" });
      if (res.in_watchlist) {
        state.watchlist.add(movieId);
      } else {
        state.watchlist.delete(movieId);
      }
      updateWatchlistButtons();
    } catch (e) {
      alert(e.message);
    }
  }

  // --- Hero Slider ---
  function renderHeroSlider(movies) {
    const slider = byId("hero-slider");
    const indContainer = byId("hero-indicators");
    slider.innerHTML = "";
    indContainer.innerHTML = "";

    if (!movies || !movies.length) return;

    movies.forEach((m, idx) => {
      const slide = document.createElement("div");
      slide.className = `hero-slide ${idx === 0 ? "active" : ""}`;
      slide.dataset.index = idx;

      const backdrop = m.backdrop_url || m.poster_url;
      slide.innerHTML = `
        <img class="hero-backdrop-img" src="${escapeHtml(backdrop)}" alt="${escapeHtml(m.title)} backdrop" loading="eager">
        <div class="hero-overlay-gradient"></div>
        <div class="hero-content">
          <div class="hero-meta-row">
            <span class="badge-tag rating-gold">★ ${Number(m.rating || 8.0).toFixed(1)}</span>
            <span class="badge-tag format-imax">IMAX LASER</span>
            <span class="badge-tag">${escapeHtml((m.genres || [])[0] || "Cinema")}</span>
            <span class="badge-tag">${escapeHtml(m.duration || "140 min")}</span>
            <span class="badge-tag">${escapeHtml(m.age_rating || "UA")}</span>
          </div>
          <h1 class="hero-title">${escapeHtml(m.title)}</h1>
          <p class="hero-synopsis">${escapeHtml(m.description)}</p>
          <div class="hero-actions">
            <button class="btn-primary" onclick="window.Cinepass.startBooking('${m.id}')">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="2" y="4" width="20" height="16" rx="2"></rect><line x1="2" y1="10" x2="22" y2="10"></line></svg>
              Book Tickets
            </button>
            <button class="btn-secondary" onclick="window.Cinepass.openTrailer('${escapeHtml(m.trailer_url || '')}')">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
              Watch Trailer
            </button>
            <button class="btn-secondary" onclick="window.Cinepass.openMovieDetails('${m.id}')">
              Details
            </button>
          </div>
        </div>
      `;
      slider.appendChild(slide);

      const dot = document.createElement("div");
      dot.className = `hero-dot ${idx === 0 ? "active" : ""}`;
      dot.onclick = () => setHeroSlide(idx);
      indContainer.appendChild(dot);
    });

    clearInterval(state.heroTimer);
    state.heroTimer = setInterval(() => {
      const next = (state.activeHeroIndex + 1) % movies.length;
      setHeroSlide(next);
    }, 6000);
  }

  function setHeroSlide(idx) {
    state.activeHeroIndex = idx;
    qAll(".hero-slide").forEach((s, i) => s.classList.toggle("active", i === idx));
    qAll(".hero-dot").forEach((d, i) => d.classList.toggle("active", i === idx));
  }

  // --- Movie Card Renderer ---
  function createMovieCard(m) {
    const card = document.createElement("article");
    card.className = "movie-card";
    card.dataset.id = m.id;

    const rating = Number(m.rating || 0).toFixed(1);
    const poster = m.poster_url || "/static/images/movie-placeholder.svg";
    const genres = (m.genres || []).slice(0, 2).join(" • ");

    card.innerHTML = `
      <div class="card-poster-wrap">
        <img src="${escapeHtml(poster)}" alt="${escapeHtml(m.title)} poster" loading="lazy" onerror="this.src='/static/images/movie-placeholder.svg'">
        <div class="card-rating-badge">★ ${rating}</div>
        <div class="card-age-badge">${escapeHtml(m.age_rating || "UA")}</div>
        <div class="card-overlay-actions">
          <button class="btn-secondary btn-sm" onclick="window.Cinepass.openMovieDetails('${m.id}')">View Details</button>
        </div>
      </div>
      <div class="card-body">
        <h3 class="card-title" title="${escapeHtml(m.title)}">${escapeHtml(m.title)}</h3>
        <p class="card-genres">${escapeHtml(genres)} • ${escapeHtml(m.language || "English")}</p>
        <div class="card-footer">
          <button class="btn-book-card" onclick="window.Cinepass.startBooking('${m.id}')">Book Tickets</button>
          <button class="btn-watchlist-card" data-movie-watchlist-id="${m.id}" title="Add to Watchlist" onclick="window.Cinepass.toggleWatchlist('${m.id}', this)">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path></svg>
          </button>
        </div>
      </div>
    `;
    return card;
  }

  // --- Homepage Data Loader ---
  async function loadHomepage() {
    try {
      const res = await api("/api/movies/homepage");
      const data = res.data;
      state.homepageData = data;

      // Populate hero carousel
      renderHeroSlider(data.hero_carousel);

      // Populate Now Showing
      const nowGrid = byId("now-showing-grid");
      nowGrid.innerHTML = "";
      data.now_showing.forEach((m) => {
        state.movies.set(m.id, m);
        nowGrid.appendChild(createMovieCard(m));
      });

      // Populate Trending
      const trendGrid = byId("trending-grid");
      trendGrid.innerHTML = "";
      data.trending.forEach((m) => {
        state.movies.set(m.id, m);
        trendGrid.appendChild(createMovieCard(m));
      });

      // Populate Coming Soon
      const soonGrid = byId("coming-soon-grid");
      soonGrid.innerHTML = "";
      data.coming_soon.forEach((m) => {
        state.movies.set(m.id, m);
        soonGrid.appendChild(createMovieCard(m));
      });

      // Populate Genre & Language filters
      const genreSelect = byId("filter-genre");
      genreSelect.innerHTML = '<option value="all">All Genres</option>';
      data.available_genres.forEach((g) => {
        genreSelect.innerHTML += `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`;
      });

      const langSelect = byId("filter-language");
      langSelect.innerHTML = '<option value="all">All Languages</option>';
      data.available_languages.forEach((l) => {
        langSelect.innerHTML += `<option value="${escapeHtml(l)}">${escapeHtml(l)}</option>`;
      });

      loadPersonalizedRecommendations();
      loadDiscovery();
    } catch (e) {
      console.error("Homepage load failed:", e);
    }
  }

  async function loadPersonalizedRecommendations() {
    try {
      const res = await api("/api/ai/personalized?limit=8");
      const grid = byId("personalized-grid");
      grid.innerHTML = "";
      if (res.recommendations && res.recommendations.length) {
        res.recommendations.forEach((m) => {
          state.movies.set(m.id, m);
          grid.appendChild(createMovieCard(m));
        });
      }
    } catch (e) {
      console.warn("Personalized recs failed:", e);
    }
  }

  // --- Catalog Discovery & Filtering ---
  async function loadDiscovery(page = 1) {
    const genre = byId("filter-genre").value;
    const language = byId("filter-language").value;
    const minRating = byId("filter-rating").value;
    const sortBy = byId("filter-sort").value;

    const params = new URLSearchParams({
      page,
      limit: 12,
      sort_by: sortBy,
    });
    if (genre !== "all") params.append("genre", genre);
    if (language !== "all") params.append("language", language);
    if (minRating > 0) params.append("min_rating", minRating);

    try {
      const res = await api(`/api/movies/discover?${params.toString()}`);
      const grid = byId("discovery-grid");
      grid.innerHTML = "";

      if (!res.movies || !res.movies.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;text-align:center;padding:40px;color:#94a3b8;">No movies match the selected filters.</div>';
      } else {
        res.movies.forEach((m) => {
          state.movies.set(m.id, m);
          grid.appendChild(createMovieCard(m));
        });
      }
      byId("discovery-total-count").textContent = `Showing ${res.movies.length} of ${res.total_count} movies`;
    } catch (e) {
      console.error("Discovery error:", e);
    }
  }

  // --- Featured Cinemas ---
  async function loadCinemas() {
    try {
      const res = await api(`/api/cinemas?city=${encodeURIComponent(state.selectedCity)}`);
      const grid = byId("cinemas-grid");
      grid.innerHTML = "";

      if (!res.cinemas || !res.cinemas.length) {
        grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;text-align:center;padding:40px;color:#94a3b8;">No partner cinemas found in ${escapeHtml(state.selectedCity)}. Please select another city.</div>`;
        return;
      }

      res.cinemas.forEach((c) => {
        state.cinemas.set(c.id, c);
        const card = document.createElement("article");
        card.className = "cinema-card";
        const amenitiesHtml = (c.amenities || [])
          .map((a) => `<span class="amenity-chip">${escapeHtml(a)}</span>`)
          .join("");

        card.innerHTML = `
          <img class="cinema-card-img" src="${escapeHtml(c.image_url)}" alt="${escapeHtml(c.name)}" loading="lazy">
          <div class="cinema-card-body">
            <h4>${escapeHtml(c.name)}</h4>
            <p class="cinema-location-text">📍 ${escapeHtml(c.location || c.city)} &bull; ★ ${Number(c.rating || 4.5).toFixed(1)}</p>
            <div class="cinema-amenities-tags">${amenitiesHtml}</div>
            <div class="cinema-actions">
              <button class="btn-primary btn-sm btn-block" onclick="window.Cinepass.openCinemaShows('${c.id}')">View Showtimes</button>
            </div>
          </div>
        `;
        grid.appendChild(card);
      });
    } catch (e) {
      console.error("Failed to load cinemas:", e);
    }
  }

  // --- Live Search Autocomplete ---
  let searchDebounceTimer = null;
  byId("global-search-input").addEventListener("input", (e) => {
    clearTimeout(searchDebounceTimer);
    const q = e.target.value.trim();
    const dropdown = byId("search-autocomplete-dropdown");

    if (q.length < 2) {
      dropdown.hidden = true;
      return;
    }

    searchDebounceTimer = setTimeout(async () => {
      try {
        const res = await api(`/api/movies/suggestions?q=${encodeURIComponent(q)}`);
        dropdown.innerHTML = "";
        if (!res.suggestions || !res.suggestions.length) {
          dropdown.innerHTML = '<div style="padding:12px;font-size:0.85rem;color:#94a3b8;">No matching movies found</div>';
        } else {
          res.suggestions.forEach((item) => {
            const div = document.createElement("div");
            div.className = "autocomplete-item";
            div.innerHTML = `
              <img class="autocomplete-thumb" src="${escapeHtml(item.poster_url || '/static/images/movie-placeholder.svg')}" alt="${escapeHtml(item.title)}">
              <div class="autocomplete-info">
                <h5>${escapeHtml(item.title)}</h5>
                <p>${escapeHtml(item.year || "")} &bull; ${escapeHtml((item.genres || [])[0] || "")} &bull; ★ ${Number(item.rating || 0).toFixed(1)}</p>
              </div>
            `;
            div.onclick = () => {
              dropdown.hidden = true;
              window.Cinepass.openMovieDetails(item.id);
            };
            dropdown.appendChild(div);
          });
        }
        dropdown.hidden = false;
      } catch (e) {
        console.warn("Search autocomplete error:", e);
      }
    }, 240);
  });

  // --- Movie Details Modal ---
  async function openMovieDetails(movieId) {
    try {
      const res = await api(`/api/movies/${movieId}`);
      const m = res.movie;
      const sim = res.similar_movies || [];

      const container = byId("movie-details-content");
      const poster = m.poster_url || "/static/images/movie-placeholder.svg";
      const castList = (m.cast || []).join(", ");
      const genres = (m.genres || []).join(" • ");

      container.innerHTML = `
        <div class="details-poster-wrap">
          <img src="${escapeHtml(poster)}" alt="${escapeHtml(m.title)} poster">
        </div>
        <div class="details-info-wrap">
          <h2 class="details-title">${escapeHtml(m.title)}</h2>
          <div class="details-meta-line">
            <span class="badge-tag rating-gold">★ ${Number(m.rating || 8.0).toFixed(1)}</span>
            <span>${escapeHtml(m.year)}</span>
            <span>${escapeHtml(m.duration)}</span>
            <span>${escapeHtml(m.language)}</span>
            <span>${escapeHtml(m.age_rating || "UA")}</span>
          </div>
          <p class="text-accent" style="font-weight:700;margin-bottom:14px;">${escapeHtml(genres)}</p>
          <div class="details-actions-row">
            <button class="btn-primary" onclick="window.Cinepass.startBooking('${m.id}')">Book Tickets Now</button>
            <button class="btn-secondary" onclick="window.Cinepass.openTrailer('${escapeHtml(m.trailer_url || '')}')">Watch Trailer</button>
            <button class="btn-secondary" onclick="window.Cinepass.toggleWatchlist('${m.id}')">Watchlist</button>
          </div>
          <p class="details-synopsis">${escapeHtml(m.description)}</p>
          <div class="details-credits-grid">
            <div class="credit-item">
              <strong>Director</strong>
              <span>${escapeHtml(m.director || "Unknown")}</span>
            </div>
            <div class="credit-item">
              <strong>Starring</strong>
              <span>${escapeHtml(castList || "Ensemble Cast")}</span>
            </div>
          </div>
        </div>
      `;
      openModal("movie-details-modal");
    } catch (e) {
      alert("Could not load movie details: " + e.message);
    }
  }

  function openTrailer(trailerUrl) {
    if (!trailerUrl) {
      alert("Trailer is currently unavailable for this title.");
      return;
    }
    let embedUrl = trailerUrl;
    if (trailerUrl.includes("watch?v=")) {
      embedUrl = trailerUrl.replace("watch?v=", "embed/").split("&")[0];
    } else if (trailerUrl.includes("youtu.be/")) {
      const vidId = trailerUrl.split("youtu.be/")[1]?.split("?")[0];
      embedUrl = `https://www.youtube.com/embed/${vidId}`;
    }
    const sep = embedUrl.includes("?") ? "&" : "?";
    byId("trailer-iframe-wrap").innerHTML = `
      <iframe width="100%" height="500" src="${escapeHtml(embedUrl)}${sep}autoplay=1&enablejsapi=1" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
    `;
    openModal("trailer-modal");
  }

  // ==========================================================================
  // COMPLETE 4-STEP TICKET BOOKING WORKFLOW
  // ==========================================================================

  async function startBooking(movieId) {
    closeModal("trailer-modal");
    closeModal("movie-details-modal");
    stopTrailer();
    resetBookingState();

    let movie = state.movies.get(movieId);
    if (!movie) {
      const res = await api(`/api/movies/${movieId}`);
      movie = res.movie;
      state.movies.set(movieId, movie);
    }

    byId("booking-movie-title").textContent = movie.title;
    byId("booking-movie-meta").textContent = `${movie.language || "English"} • ${movie.duration || "140 min"} • ${state.selectedCity}`;

    // Set step indicators
    setBookingStep(1);
    openModal("booking-modal");
    loadShowtimesForMovie(movieId);
  }

  function resetBookingState() {
    state.booking = {
      show: null,
      selectedDate: null,
      selectedSeats: new Set(),
      lockedSeatIds: [],
      lockTimerInterval: null,
      lockExpiresAt: null,
      snacks: new Map(),
      couponCode: null,
      couponDiscount: 0,
      breakdown: null,
      orderData: null,
    };
    clearInterval(state.booking.lockTimerInterval);
    byId("seat-lock-timer-box").hidden = true;
    byId("btn-proceed-to-snacks").disabled = true;
  }

  function setBookingStep(step) {
    [1, 2, 3, 4].forEach((s) => {
      byId(`indicator-step-${s}`).classList.toggle("active", s === step);
    });

    byId("booking-step-showtimes").hidden = step !== 1;
    byId("booking-step-seats").hidden = step !== 2;
    byId("booking-step-snacks").hidden = step !== 3;
    byId("booking-step-checkout").hidden = step !== 4;
  }

  // STEP 1: Load Showtimes
  async function loadShowtimesForMovie(movieId) {
    // Generate next 5 date tabs
    const dateTabsWrap = byId("booking-date-tabs");
    dateTabsWrap.innerHTML = "";
    const today = new Date();

    const dates = [];
    for (let i = 0; i < 5; i++) {
      const d = new Date(today);
      d.setDate(today.getDate() + i);
      const iso = d.toISOString().split("T")[0];
      const dayName = i === 0 ? "Today" : i === 1 ? "Tomorrow" : d.toLocaleDateString("en-US", { weekday: "short" });
      const dateStr = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      dates.push({ iso, dayName, dateStr });
    }

    state.booking.selectedDate = dates[0].iso;

    dates.forEach((d, idx) => {
      const btn = document.createElement("button");
      btn.className = `date-tab-btn ${idx === 0 ? "active" : ""}`;
      btn.innerHTML = `<strong>${d.dayName}</strong><br><small>${d.dateStr}</small>`;
      btn.onclick = () => {
        qAll(".date-tab-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.booking.selectedDate = d.iso;
        fetchShowsForDate(movieId, d.iso);
      };
      dateTabsWrap.appendChild(btn);
    });

    fetchShowsForDate(movieId, dates[0].iso);
  }

  async function fetchShowsForDate(movieId, date) {
    const listWrap = byId("booking-cinema-shows");
    listWrap.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">Finding theatres and showtimes...</div>';

    try {
      const res = await api(`/api/shows?movie_id=${movieId}&city=${encodeURIComponent(state.selectedCity)}&date=${date}`);
      listWrap.innerHTML = "";

      if (!res.shows || !res.shows.length) {
        listWrap.innerHTML = `<div class="empty-state" style="padding:30px;text-align:center;color:#94a3b8;">No showtimes scheduled for this date in ${escapeHtml(state.selectedCity)}. Please try another date or location.</div>`;
        return;
      }

      // Group shows by cinema
      const cinemaGroups = new Map();
      res.shows.forEach((s) => {
        const cName = s.cinema ? s.cinema.name : "Cinema Multiplex";
        if (!cinemaGroups.has(cName)) cinemaGroups.set(cName, []);
        cinemaGroups.get(cName).push(s);
      });

      cinemaGroups.forEach((shows, cName) => {
        const card = document.createElement("div");
        card.className = "cinema-show-card";
        const cAddress = shows[0].cinema?.address || state.selectedCity;
        const pillsHtml = shows
          .map((s) => `
            <button class="showtime-pill-btn" onclick="window.Cinepass.selectShowtime('${s.id}')">
              ${escapeHtml(s.start_time)}
              <small style="display:block;font-size:0.68rem;opacity:0.8;">${escapeHtml(s.screen?.screen_type || "2D")}</small>
            </button>
          `)
          .join("");

        card.innerHTML = `
          <h4>${escapeHtml(cName)}</h4>
          <p class="cinema-location-text">📍 ${escapeHtml(cAddress)}</p>
          <div class="showtimes-pills-row">${pillsHtml}</div>
        `;
        listWrap.appendChild(card);
      });
    } catch (e) {
      listWrap.innerHTML = `<div style="padding:20px;color:#f43f5e;">Error: ${e.message}</div>`;
    }
  }

  // STEP 2: Seat Map & Real-time Atomic Locking
  async function selectShowtime(showId) {
    try {
      const res = await api(`/api/shows/${showId}`);
      state.booking.show = res.show;

      byId("seatmap-cinema-info").textContent = `${res.show.cinema?.name || "Cinema"} • ${res.show.screen?.screen_name || "Screen 1"}`;
      byId("seatmap-time-info").textContent = `${res.show.date} • ${res.show.start_time} (${res.show.screen?.screen_type || "Standard"})`;

      await loadSeatMap(showId);
      setBookingStep(2);
    } catch (e) {
      alert("Could not load show: " + e.message);
    }
  }

  async function loadSeatMap(showId) {
    const matrix = byId("seat-layout-matrix");
    matrix.innerHTML = '<div style="padding:30px;color:#94a3b8;">Loading cinema seat layout...</div>';

    try {
      const res = await api(`/api/bookings/layout/${showId}`);
      matrix.innerHTML = "";

      res.sections.forEach((sec) => {
        const tierHeader = document.createElement("div");
        tierHeader.className = "seat-tier-header";
        tierHeader.textContent = `${sec.label} — ${formatCurrency(sec.price)}`;
        matrix.appendChild(tierHeader);

        sec.rows.forEach((r) => {
          const rowDiv = document.createElement("div");
          rowDiv.className = "seat-row";

          const label = document.createElement("span");
          label.className = "seat-row-label";
          label.textContent = r.row;
          rowDiv.appendChild(label);

          r.seats.forEach((seat) => {
            const btn = document.createElement("button");
            btn.className = `seat-btn ${seat.status}`;
            btn.dataset.seatId = seat.id;
            btn.dataset.price = seat.price;
            btn.dataset.tier = seat.tier;
            btn.textContent = seat.number;
            btn.title = `${seat.id} (${seat.tier}) - ${formatCurrency(seat.price)}`;

            if (seat.status === "available" || seat.status === "selected") {
              btn.onclick = () => toggleSeatSelection(btn, seat);
            } else if (seat.status === "booked") {
              btn.disabled = true;
            } else if (seat.status === "locked") {
              btn.disabled = true;
            }

            rowDiv.appendChild(btn);
          });
          matrix.appendChild(rowDiv);
        });
      });
      updateSelectedSeatsBar();
    } catch (e) {
      matrix.innerHTML = `<div style="padding:30px;color:#f43f5e;">${e.message}</div>`;
    }
  }

  function toggleSeatSelection(btn, seat) {
    const sid = seat.id;
    if (state.booking.selectedSeats.has(sid)) {
      state.booking.selectedSeats.delete(sid);
      btn.classList.remove("selected");
    } else {
      if (state.booking.selectedSeats.size >= 10) {
        alert("You can select a maximum of 10 seats per booking.");
        return;
      }
      state.booking.selectedSeats.add(sid);
      btn.classList.add("selected");
    }
    updateSelectedSeatsBar();
  }

  function updateSelectedSeatsBar() {
    const count = state.booking.selectedSeats.size;
    const barSeats = byId("bar-selected-seats");
    const barPrice = byId("bar-subtotal-price");
    const proceedBtn = byId("btn-proceed-to-snacks");

    if (count === 0) {
      barSeats.textContent = "None selected";
      barPrice.textContent = "₹0.00";
      proceedBtn.disabled = true;
    } else {
      const seatArr = [...state.booking.selectedSeats];
      barSeats.textContent = seatArr.join(", ");
      let total = 0;
      seatArr.forEach((sid) => {
        const btn = document.querySelector(`[data-seat-id="${sid}"]`);
        if (btn) total += Number(btn.dataset.price || 0);
      });
      barPrice.textContent = formatCurrency(total);
      proceedBtn.disabled = false;
    }
  }

  // STEP 2 -> STEP 3: Lock Seats on Server & Start 8-Min Countdown
  byId("btn-proceed-to-snacks").onclick = async () => {
    if (!state.user) {
      openModal("auth-modal");
      return;
    }

    const seatIds = [...state.booking.selectedSeats];
    const showId = state.booking.show.id;

    try {
      const lockRes = await api("/api/bookings/lock-seats", {
        method: "POST",
        body: JSON.stringify({ show_id: showId, seat_ids: seatIds }),
      });

      state.booking.lockedSeatIds = seatIds;
      startLockCountdown(lockRes.timeout_seconds || 480);
      await loadSnacksMenu(state.booking.show.cinema_id);
      setBookingStep(3);
    } catch (e) {
      alert("Seat locking error: " + e.message);
      loadSeatMap(showId);
    }
  };

  function startLockCountdown(seconds) {
    clearInterval(state.booking.lockTimerInterval);
    let remaining = seconds;
    const timerBox = byId("seat-lock-timer-box");
    const countdownLabel = byId("lock-countdown");
    timerBox.hidden = false;

    function renderTime() {
      const mins = Math.floor(remaining / 60);
      const secs = remaining % 60;
      countdownLabel.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }

    renderTime();
    state.booking.lockTimerInterval = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(state.booking.lockTimerInterval);
        alert("Your 8-minute seat reservation has expired. Please select your seats again.");
        resetBookingState();
        setBookingStep(1);
      } else {
        renderTime();
      }
    }, 1000);
  }

  // STEP 3: Concession Snacks
  async function loadSnacksMenu(cinemaId) {
    try {
      const res = await api(`/api/cinemas/${cinemaId}/snacks`);
      const grid = byId("snacks-selection-grid");
      grid.innerHTML = "";

      (res.snacks || []).forEach((snk) => {
        const card = document.createElement("div");
        card.className = "snack-card";
        card.innerHTML = `
          <img class="snack-card-img" src="${escapeHtml(snk.image_url)}" alt="${escapeHtml(snk.name)}">
          <div class="snack-card-info">
            <h5>${escapeHtml(snk.name)}</h5>
            <span class="snack-price">${formatCurrency(snk.price)}</span>
            <div class="snack-qty-control">
              <button class="btn-qty" type="button" onclick="window.Cinepass.adjustSnack('${snk.id}', -1)">-</button>
              <strong id="snk-qty-${snk.id}">0</strong>
              <button class="btn-qty" type="button" onclick="window.Cinepass.adjustSnack('${snk.id}', 1)">+</button>
            </div>
          </div>
        `;
        grid.appendChild(card);
      });
      updateSnacksBottomBar();
    } catch (e) {
      console.warn("Snacks menu error:", e);
    }
  }

  function adjustSnack(snkId, delta) {
    const current = state.booking.snacks.get(snkId) || { id: snkId, quantity: 0 };
    const newQty = Math.max(0, current.quantity + delta);
    if (newQty === 0) {
      state.booking.snacks.delete(snkId);
    } else {
      state.booking.snacks.set(snkId, { id: snkId, quantity: newQty });
    }
    const label = byId(`snk-qty-${snkId}`);
    if (label) label.textContent = newQty;
    updateSnacksBottomBar();
  }

  function updateSnacksBottomBar() {
    let count = 0;
    state.booking.snacks.forEach((v) => (count += v.quantity));
    byId("snacks-count-label").textContent = `${count} items added`;
  }

  // STEP 3 -> STEP 4: Review Summary, Calculate Backend Pricing & Display Checkout
  byId("btn-proceed-to-checkout").onclick = async () => {
    await refreshOrderBreakdown();
    setBookingStep(4);
  };

  async function refreshOrderBreakdown() {
    const showId = state.booking.show.id;
    const seatIds = [...state.booking.selectedSeats];
    const snacksArr = Array.from(state.booking.snacks.values());

    try {
      const res = await api("/api/bookings/calculate", {
        method: "POST",
        body: JSON.stringify({
          show_id: showId,
          seat_ids: seatIds,
          snacks: snacksArr,
          coupon_code: state.booking.couponCode,
        }),
      });

      const b = res.breakdown;
      state.booking.breakdown = b;

      byId("chk-movie-name").textContent = b.show.movie?.title || "Movie";
      byId("chk-ticket-qty").textContent = `${b.num_tickets} Tickets`;
      byId("chk-seats-list").textContent = `Seats: ${seatIds.join(", ")}`;
      byId("chk-ticket-subtotal").textContent = formatCurrency(b.ticket_subtotal);

      if (b.snack_subtotal > 0) {
        byId("chk-snacks-section").hidden = false;
        byId("chk-snacks-subtotal").textContent = formatCurrency(b.snack_subtotal);
      } else {
        byId("chk-snacks-section").hidden = true;
      }

      byId("chk-convenience-fee").textContent = formatCurrency(b.convenience_fee);
      byId("chk-gst").textContent = formatCurrency(b.gst);

      if (b.coupon_discount > 0) {
        byId("chk-discount-line").hidden = false;
        byId("chk-discount").textContent = `-${formatCurrency(b.coupon_discount)}`;
      } else {
        byId("chk-discount-line").hidden = true;
      }

      byId("chk-final-total").textContent = formatCurrency(b.total_amount);
      byId("btn-pay-amount-label").textContent = formatCurrency(b.total_amount);

      // Prepare order with Razorpay test mode
      const orderRes = await api("/api/payments/create-order", {
        method: "POST",
        body: JSON.stringify({
          show_id: showId,
          seat_ids: seatIds,
          snacks: snacksArr,
          coupon_code: state.booking.couponCode,
        }),
      });

      state.booking.orderData = orderRes;
      byId("rzp-order-id-label").textContent = orderRes.order_id;
    } catch (e) {
      alert("Pricing calculation error: " + e.message);
    }
  }

  // Apply Promo Coupon
  byId("btn-apply-coupon").onclick = async () => {
    const code = byId("coupon-input").value.trim().toUpperCase();
    if (!code) return;
    state.booking.couponCode = code;
    await refreshOrderBreakdown();
    if (state.booking.breakdown?.coupon_message) {
      byId("coupon-status-msg").textContent = state.booking.breakdown.coupon_message;
    }
  };

  // STEP 4: Razorpay Test Checkout Verification
  byId("btn-confirm-payment").onclick = async () => {
    const btn = byId("btn-confirm-payment");
    btn.disabled = true;
    btn.textContent = "Verifying Payment with Razorpay...";

    const order = state.booking.orderData;
    if (!order) {
      alert("Order initialization error.");
      btn.disabled = false;
      return;
    }

    try {
      // Simulate realistic payment verification
      const paymentId = `pay_${Math.random().toString(36).substring(2, 14)}`;
      // Call backend verification endpoint
      const verifyRes = await api("/api/payments/verify", {
        method: "POST",
        body: JSON.stringify({
          razorpay_order_id: order.order_id,
          razorpay_payment_id: paymentId,
          razorpay_signature: "simulated_signature",
          simulate_success_for_test: true,
        }),
      });

      // Clear seat lock timer
      clearInterval(state.booking.lockTimerInterval);
      closeModal("booking-modal");

      // Display Digital Ticket
      displayDigitalTicket(verifyRes.booking);

      // Refresh User Bookings so they appear in Dashboard
      if (state.user) {
        loadUserBookings().catch(() => {});
      }
    } catch (e) {
      alert("Payment failed: " + e.message);
      await api("/api/payments/failed", {
        method: "POST",
        body: JSON.stringify({ order_id: order.order_id, reason: e.message }),
      });
    } finally {
      btn.disabled = false;
      btn.innerHTML = `Pay <span id="btn-pay-amount-label">${formatCurrency(state.booking.breakdown?.total_amount || 0)}</span> Securely`;
    }
  };

  byId("btn-cancel-checkout").onclick = async () => {
    if (confirm("Are you sure you want to cancel? Your selected seats will be released.")) {
      if (state.booking.show && state.booking.lockedSeatIds.length) {
        await api("/api/bookings/unlock-seats", {
          method: "POST",
          body: JSON.stringify({
            show_id: state.booking.show.id,
            seat_ids: state.booking.lockedSeatIds,
          }),
        }).catch(() => {});
      }
      resetBookingState();
      closeModal("booking-modal");
    }
  };

  // --- Digital Ticket Display ---
  function displayDigitalTicket(booking) {
    if (!booking) {
      alert("Ticket details could not be loaded.");
      return;
    }
    const wrap = byId("digital-ticket-wrapper");
    if (!wrap) return;

    let seatNames = "";
    if (Array.isArray(booking.seats)) {
      seatNames = booking.seats.map((s) => (typeof s === "object" ? s.seat_id || s.seat || "" : s)).filter(Boolean).join(", ");
    }
    if (!seatNames && Array.isArray(booking.seat_ids)) {
      seatNames = booking.seat_ids.join(", ");
    }
    if (!seatNames) seatNames = "Confirmed Seats";

    const qrData = booking.qr_code_data || "";
    const refCode = booking.booking_reference || booking.id || "CONFIRMED";

    wrap.innerHTML = `
      <div class="ticket-header-band">
        <div class="ticket-brand">CINEPASS CONFIRMED PASS</div>
        <div class="ticket-ref-pill">${escapeHtml(refCode)}</div>
      </div>
      <div class="ticket-body-details">
        <div>
          <h2 class="ticket-movie-name">${escapeHtml(booking.movie_title || "Cinema Movie")}</h2>
          <p class="ticket-cinema-meta">📍 ${escapeHtml(booking.cinema_name || "Cinema")}${booking.cinema_city ? ", " + escapeHtml(booking.cinema_city) : ""}</p>
          <div class="ticket-grid-meta">
            <div>
              <strong style="display:block;color:#64748b;font-size:0.75rem;">DATE &amp; TIME</strong>
              <span>${escapeHtml(booking.show_date || "Today")} &bull; ${escapeHtml(booking.show_time || "")}</span>
            </div>
            <div>
              <strong style="display:block;color:#64748b;font-size:0.75rem;">SCREEN &amp; FORMAT</strong>
              <span>${escapeHtml(booking.screen_name || "Screen 1")} (${escapeHtml(booking.screen_type || "Standard")})</span>
            </div>
            <div>
              <strong style="display:block;color:#64748b;font-size:0.75rem;">SEATS</strong>
              <span style="font-weight:700;color:var(--primary);">${escapeHtml(seatNames)}</span>
            </div>
            <div>
              <strong style="display:block;color:#64748b;font-size:0.75rem;">TOTAL PAID</strong>
              <span style="font-weight:700;">${formatCurrency(booking.total_amount || 0)}</span>
            </div>
          </div>
        </div>
        <div class="ticket-qr-container">
          ${qrData ? `<img class="ticket-qr-img" src="${escapeHtml(qrData)}" alt="QR Code for Ticket Verification">` : `<div style="width:130px;height:130px;background:#eee;border-radius:6px;display:grid;place-items:center;color:#333;font-size:0.75rem;text-align:center;padding:8px;"><b>VERIFIED PASS</b><br><small>${escapeHtml(refCode)}</small></div>`}
          <span class="qr-caption">Scan at Entrance</span>
        </div>
      </div>
    `;
    openModal("ticket-modal");
  }

  byId("btn-print-ticket").onclick = () => window.print();
  byId("btn-ticket-done").onclick = () => closeModal("ticket-modal");

  // --- Step Navigation Buttons ---
  byId("btn-back-to-shows").onclick = () => setBookingStep(1);
  byId("btn-back-to-seats").onclick = () => setBookingStep(2);
  byId("btn-back-to-snacks").onclick = () => setBookingStep(3);

  // --- CineBot AI Assistant Drawer ---
  const cinebotTrigger = byId("floating-cinebot-trigger");
  const cinebotDrawer = byId("cinebot-drawer");
  const btnCloseCinebot = byId("btn-close-cinebot");
  const cinebotForm = byId("cinebot-form");
  const cinebotInput = byId("cinebot-input");
  const cinebotStream = byId("cinebot-chat-stream");

  cinebotTrigger.onclick = () => {
    cinebotDrawer.hidden = !cinebotDrawer.hidden;
    if (!cinebotDrawer.hidden) cinebotInput.focus();
  };
  btnCloseCinebot.onclick = () => (cinebotDrawer.hidden = true);
  byId("nav-cinebot-btn").onclick = () => {
    cinebotDrawer.hidden = !cinebotDrawer.hidden;
    if (!cinebotDrawer.hidden) cinebotInput.focus();
  };

  const mobileNavCinebot = byId("mobile-nav-cinebot");
  if (mobileNavCinebot) {
    mobileNavCinebot.onclick = () => {
      cinebotDrawer.hidden = !cinebotDrawer.hidden;
      if (!cinebotDrawer.hidden) cinebotInput.focus();
    };
  }

  const mobileNavProfile = byId("mobile-nav-profile");
  if (mobileNavProfile) {
    mobileNavProfile.onclick = () => {
      if (state.user) {
        openUserDashboard("bookings");
      } else {
        openModal("auth-modal");
      }
    };
  }

  // Active state for mobile bottom nav items
  qAll(".mobile-bottom-nav a").forEach((link) => {
    link.addEventListener("click", () => {
      qAll(".mobile-bottom-nav .mobile-nav-item").forEach((i) => i.classList.remove("active"));
      link.classList.add("active");
    });
  });

  // Quick Prompt Chips
  qAll(".prompt-chip").forEach((chip) => {
    chip.onclick = () => {
      cinebotInput.value = chip.textContent;
      sendCinebotMessage(chip.textContent);
    };
  });

  cinebotForm.onsubmit = (e) => {
    e.preventDefault();
    const msg = cinebotInput.value.trim();
    if (!msg) return;
    sendCinebotMessage(msg);
  };

  async function sendCinebotMessage(text) {
    cinebotInput.value = "";
    appendChatBubble(text, "user");

    const typingBubble = appendChatBubble("CineBot is thinking...", "bot");

    try {
      const res = await api("/api/ai/cinebot", {
        method: "POST",
        body: JSON.stringify({ message: text, city: state.selectedCity }),
      });

      typingBubble.remove();
      const replyDiv = appendChatBubble(res.reply, "bot");

      if (res.suggested_movies && res.suggested_movies.length) {
        const cardsDiv = document.createElement("div");
        cardsDiv.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px;";
        res.suggested_movies.slice(0, 2).forEach((m) => {
          cardsDiv.innerHTML += `
            <div style="background:#0e111a;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:8px;font-size:0.78rem;">
              <strong>${escapeHtml(m.title)}</strong><br>
              <small style="color:#94a3b8;">★ ${Number(m.rating || 8).toFixed(1)} &bull; ${escapeHtml((m.genres || [])[0])}</small><br>
              <button class="btn-primary btn-sm" style="margin-top:6px;width:100%;font-size:0.72rem;padding:4px;" onclick="window.Cinepass.startBooking('${m.id}')">Book</button>
            </div>
          `;
        });
        replyDiv.appendChild(cardsDiv);
      }
    } catch (e) {
      typingBubble.textContent = "Sorry, CineBot is currently experiencing a connection hiccup: " + e.message;
    }
  }

  function appendChatBubble(content, sender) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}-bubble`;
    bubble.innerHTML = `<p>${escapeHtml(content)}</p>`;
    cinebotStream.appendChild(bubble);
    cinebotStream.scrollTop = cinebotStream.scrollHeight;
    return bubble;
  }

  // --- User Dashboard ---
  byId("menu-my-bookings").onclick = () => openDashboard("bookings");
  byId("menu-watchlist").onclick = () => openDashboard("watchlist");
  byId("menu-profile-settings").onclick = () => openDashboard("profile");

  function openDashboard(tabName = "bookings") {
    byId("user-dropdown-panel").hidden = true;
    qAll(".dash-tab").forEach((t) => t.classList.toggle("active", t.dataset.dashTab === tabName));
    byId("dash-tab-bookings").hidden = tabName !== "bookings";
    byId("dash-tab-watchlist").hidden = tabName !== "watchlist";
    byId("dash-tab-profile").hidden = tabName !== "profile";

    if (state.user) {
      byId("dash-user-name").textContent = state.user.name;
      byId("dash-user-email").textContent = state.user.email;
      byId("dash-avatar-circle").textContent = state.user.name.charAt(0).toUpperCase();
      byId("prof-name").value = state.user.name;
      byId("prof-phone").value = state.user.phone || "";
    }

    if (tabName === "bookings") loadUserBookings();
    if (tabName === "watchlist") renderDashboardWatchlist();
    openModal("dashboard-modal");
  }

  qAll(".dash-tab").forEach((tab) => {
    tab.onclick = () => openDashboard(tab.dataset.dashTab);
  });

  async function loadUserBookings() {
    const list = byId("user-bookings-list");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">Loading bookings...</div>';

    try {
      const res = await api("/api/auth/bookings");
      list.innerHTML = "";

      if (!res.bookings || !res.bookings.length) {
        list.innerHTML = '<div class="empty-state" style="padding:40px;text-align:center;color:#94a3b8;">You have no bookings yet. Explore movies to book your first tickets!</div>';
        return;
      }

      res.bookings.forEach((b) => {
        const card = document.createElement("div");
        card.className = "user-booking-card";
        const seatNames = (b.seats || []).map((s) => s.seat_id || s).join(", ");
        const isPaid = b.payment_status === "paid";
        const isCancelled = b.ticket_status === "cancelled";

        card.innerHTML = `
          <div>
            <span class="booking-status-tag ${isCancelled ? "cancelled" : "paid"}">
              ${isCancelled ? "Cancelled &amp; Refunded" : "Confirmed &bull; Paid"}
            </span>
            <h4 style="font-size:1.15rem;margin-bottom:4px;">${escapeHtml(b.movie_title)}</h4>
            <p style="font-size:0.85rem;color:#94a3b8;">
              ${escapeHtml(b.cinema_name)} &bull; ${escapeHtml(b.show_date)} at ${escapeHtml(b.show_time)}
            </p>
            <p style="font-size:0.85rem;margin-top:6px;">
              <b>Seats:</b> ${escapeHtml(seatNames)} &bull; <b>Total:</b> ${formatCurrency(b.total_amount)}
            </p>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px;">
            ${isPaid && !isCancelled ? `
              <button class="btn-primary btn-sm" onclick="window.Cinepass.viewTicketByRef('${b.booking_reference || b.id}')">View Ticket</button>
              <button class="btn-secondary btn-sm" onclick="window.Cinepass.cancelBookingAction('${b.id}')">Cancel &amp; Refund</button>
            ` : `
              <span style="font-size:0.8rem;color:#f43f5e;">Refunded: ${formatCurrency(b.refund_amount)}</span>
            `}
          </div>
        `;
        list.appendChild(card);
      });
    } catch (e) {
      list.innerHTML = `<div style="color:#f43f5e;">Error: ${e.message}</div>`;
    }
  }

  async function cancelBookingAction(bookingId) {
    if (confirm("Cancellation Policy: 80% of ticket amount will be refunded (20% cinema cancellation fee applies). Do you wish to proceed?")) {
      try {
        const res = await api(`/api/bookings/${bookingId}/cancel`, { method: "POST" });
        alert(res.message);
        loadUserBookings();
      } catch (e) {
        alert("Cancellation failed: " + e.message);
      }
    }
  }

  async function renderDashboardWatchlist() {
    const grid = byId("user-watchlist-grid");
    grid.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8;">Loading watchlist...</div>';

    try {
      const res = await api("/api/auth/watchlist");
      grid.innerHTML = "";
      if (!res.watchlist || !res.watchlist.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;padding:40px;text-align:center;color:#94a3b8;">Your watchlist is empty.</div>';
        return;
      }
      res.watchlist.forEach((m) => {
        grid.appendChild(createMovieCard(m));
      });
    } catch (e) {
      grid.innerHTML = `<div style="color:#f43f5e;">Error: ${e.message}</div>`;
    }
  }

  // --- Profile & Password Forms ---
  byId("form-update-profile").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/auth/profile", {
        method: "PUT",
        body: JSON.stringify({
          name: byId("prof-name").value,
          phone: byId("prof-phone").value,
        }),
      });
      state.user = res.user;
      setLoggedIn(res.user);
      alert("Profile updated successfully!");
    } catch (err) {
      alert(err.message);
    }
  };

  byId("form-change-password").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/auth/password", {
        method: "PUT",
        body: JSON.stringify({
          current_password: byId("pwd-current").value,
          new_password: byId("pwd-new").value,
        }),
      });
      byId("pwd-current").value = "";
      byId("pwd-new").value = "";
      alert("Password changed successfully!");
    } catch (err) {
      alert(err.message);
    }
  };

  // --- Admin Portal ---
  byId("menu-admin-portal").onclick = () => {
    byId("user-dropdown-panel").hidden = true;
    openAdminPortal("movies");
  };

  qAll(".admin-tab").forEach((tab) => {
    tab.onclick = () => openAdminPortal(tab.dataset.adminTab);
  });

  async function openAdminPortal(tab = "movies") {
    qAll(".admin-tab").forEach((t) => t.classList.toggle("active", t.dataset.adminTab === tab));
    byId("admin-tab-movies").hidden = tab !== "movies";
    byId("admin-tab-cinemas").hidden = tab !== "cinemas";
    byId("admin-tab-shows").hidden = tab !== "shows";
    byId("admin-tab-coupons").hidden = tab !== "coupons";
    byId("admin-tab-bookings").hidden = tab !== "bookings";

    try {
      const statsRes = await api("/api/admin/stats");
      const st = statsRes.stats;
      byId("stat-revenue").textContent = formatCurrency(st.total_revenue);
      byId("stat-tickets").textContent = st.total_tickets_sold;
      byId("stat-bookings").textContent = st.total_bookings;
      byId("stat-cinemas").textContent = st.total_cinemas;

      if (tab === "movies") loadAdminMovies();
      if (tab === "shows") populateAdminShowDropdowns();
      if (tab === "bookings") loadAdminBookings();
    } catch (e) {
      alert("Admin access denied: " + e.message);
      return;
    }
    openModal("admin-modal");
  }

  async function loadAdminMovies() {
    const wrap = byId("admin-movies-table-wrap");
    try {
      const res = await api("/api/admin/movies");
      let html = '<table class="admin-table"><thead><tr><th>Title</th><th>Year</th><th>Language</th><th>Rating</th><th>Actions</th></tr></thead><tbody>';
      res.movies.forEach((m) => {
        html += `
          <tr>
            <td><b>${escapeHtml(m.title)}</b></td>
            <td>${escapeHtml(m.year)}</td>
            <td>${escapeHtml(m.language)}</td>
            <td>★ ${Number(m.rating || 0).toFixed(1)}</td>
            <td>
              <button class="btn-text-danger" style="width:auto;" onclick="window.Cinepass.adminDeleteMovie('${m.id}')">Delete</button>
            </td>
          </tr>
        `;
      });
      html += "</tbody></table>";
      wrap.innerHTML = html;
    } catch (e) {
      wrap.innerHTML = e.message;
    }
  }

  async function adminDeleteMovie(id) {
    if (confirm("Are you sure you want to delete this movie?")) {
      await api(`/api/admin/movies/${id}`, { method: "DELETE" });
      loadAdminMovies();
      loadHomepage();
    }
  }

  async function populateAdminShowDropdowns() {
    const movieSel = byId("adm-show-movie");
    const cinemaSel = byId("adm-show-cinema");
    movieSel.innerHTML = "";
    cinemaSel.innerHTML = "";

    const mRes = await api("/api/admin/movies");
    mRes.movies.forEach((m) => {
      movieSel.innerHTML += `<option value="${m.id}">${escapeHtml(m.title)}</option>`;
    });

    const cRes = await api("/api/cinemas?city=all");
    cRes.cinemas.forEach((c) => {
      cinemaSel.innerHTML += `<option value="${c.id}">${escapeHtml(c.name)} (${escapeHtml(c.city)})</option>`;
    });
  }

  byId("form-admin-schedule-show").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/admin/shows", {
        method: "POST",
        body: JSON.stringify({
          movie_id: byId("adm-show-movie").value,
          cinema_id: byId("adm-show-cinema").value,
          date: byId("adm-show-date").value,
          start_time: byId("adm-show-time").value,
        }),
      });
      alert("Show scheduled successfully!");
    } catch (err) {
      alert("Scheduling error: " + err.message);
    }
  };

  byId("form-admin-add-coupon").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/admin/coupons", {
        method: "POST",
        body: JSON.stringify({
          code: byId("adm-cp-code").value,
          discount_type: byId("adm-cp-type").value,
          discount_value: Number(byId("adm-cp-val").value),
          min_amount: Number(byId("adm-cp-min").value),
        }),
      });
      alert("Coupon created successfully!");
      byId("adm-cp-code").value = "";
    } catch (err) {
      alert("Error creating coupon: " + err.message);
    }
  };

  async function loadAdminBookings() {
    const wrap = byId("admin-bookings-table-wrap");
    try {
      const res = await api("/api/admin/bookings");
      let html = '<table class="admin-table"><thead><tr><th>Ref</th><th>User</th><th>Movie</th><th>Cinema</th><th>Amount</th><th>Status</th></tr></thead><tbody>';
      res.bookings.forEach((b) => {
        html += `
          <tr>
            <td><code>${escapeHtml(b.booking_reference)}</code></td>
            <td>${escapeHtml(b.user_name || b.user_email || "Customer")}</td>
            <td>${escapeHtml(b.movie_title)}</td>
            <td>${escapeHtml(b.cinema_name)}</td>
            <td>${formatCurrency(b.total_amount)}</td>
            <td><span class="booking-status-tag ${b.payment_status === "paid" ? "paid" : "cancelled"}">${escapeHtml(b.payment_status)}</span></td>
          </tr>
        `;
      });
      html += "</tbody></table>";
      wrap.innerHTML = html;
    } catch (e) {
      wrap.innerHTML = e.message;
    }
  }

  // --- Auth Dialog Handlers ---
  byId("btn-open-login").onclick = () => {
    byId("auth-modal-title").textContent = "Sign In to Cinepass";
    byId("tab-login").classList.add("active");
    byId("tab-register").classList.remove("active");
    byId("form-login").hidden = false;
    byId("form-register").hidden = true;
    openModal("auth-modal");
  };

  byId("btn-open-register").onclick = () => {
    byId("auth-modal-title").textContent = "Create Cinepass Account";
    byId("tab-register").classList.add("active");
    byId("tab-login").classList.remove("active");
    byId("form-register").hidden = false;
    byId("form-login").hidden = true;
    openModal("auth-modal");
  };

  byId("tab-login").onclick = byId("btn-open-login").onclick;
  byId("tab-register").onclick = byId("btn-open-register").onclick;

  byId("form-login").onsubmit = async (e) => {
    e.preventDefault();
    const email = byId("login-email").value.trim();
    const password = byId("login-password").value;
    const errEl = byId("login-error-msg");
    errEl.textContent = "";

    try {
      const res = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("cinepass_token", res.token);
      setLoggedIn(res.user);
      closeModal("auth-modal");
    } catch (err) {
      errEl.textContent = err.message;
    }
  };

  byId("form-register").onsubmit = async (e) => {
    e.preventDefault();
    const name = byId("reg-name").value.trim();
    const email = byId("reg-email").value.trim();
    const phone = byId("reg-phone").value.trim();
    const password = byId("reg-password").value;
    const errEl = byId("reg-error-msg");
    errEl.textContent = "";

    try {
      const res = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ name, email, phone, password }),
      });
      localStorage.setItem("cinepass_token", res.token);
      setLoggedIn(res.user);
      closeModal("auth-modal");
    } catch (err) {
      errEl.textContent = err.message;
    }
  };

  byId("user-avatar-btn").onclick = () => {
    const p = byId("user-dropdown-panel");
    p.hidden = !p.hidden;
  };

  byId("menu-logout").onclick = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setLoggedOut();
  };

  // Filter Bar Triggers
  ["filter-genre", "filter-language", "filter-rating", "filter-sort"].forEach((id) => {
    byId(id).addEventListener("change", () => loadDiscovery(1));
  });

  byId("btn-reset-filters").onclick = () => {
    byId("filter-genre").value = "all";
    byId("filter-language").value = "all";
    byId("filter-rating").value = "0";
    byId("filter-sort").value = "rating_desc";
    loadDiscovery(1);
  };

  byId("city-selector-btn").onclick = () => openModal("city-modal");

  // Genre Bar Chips
  qAll(".genre-pill").forEach((pill) => {
    pill.onclick = () => {
      qAll(".genre-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      const g = pill.dataset.genre;
      byId("filter-genre").value = g;
      loadDiscovery(1);
      document.getElementById("discovery-section").scrollIntoView({ behavior: "smooth" });
    };
  });

  // Stop trailer on internal anchor navigation
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", () => {
      closeModal("trailer-modal");
      stopTrailer();
    });
  });

  // Global Helpers on window.Cinepass
  window.Cinepass = {
    startBooking,
    openMovieDetails,
    openTrailer,
    stopTrailer,
    toggleWatchlist,
    selectShowtime,
    adjustSnack,
    openCinemaShows: (cinemaId) => {
      document.getElementById("now-showing").scrollIntoView({ behavior: "smooth" });
    },
    viewTicketByRef: async (ref) => {
      try {
        if (!ref) {
          alert("Ticket reference missing.");
          return;
        }
        const res = await api(`/api/tickets/${encodeURIComponent(ref)}`);
        if (res && res.ticket) {
          displayDigitalTicket(res.ticket);
        } else {
          alert("Ticket not found for reference: " + ref);
        }
      } catch (err) {
        alert("Failed to load ticket: " + (err.message || "Unknown error"));
      }
    },
    cancelBookingAction,
    adminDeleteMovie,
  };

  window.copyCoupon = (code) => {
    navigator.clipboard.writeText(code).then(() => {
      alert(`Coupon code '${code}' copied! Apply it at checkout for instant discount.`);
    });
  };

  // Initialization Sequence
  cinebotDrawer.hidden = true;
  byId("current-city-label").textContent = state.selectedCity;
  byId("cinema-city-heading").textContent = state.selectedCity;
  loadCities();
  checkAuth();
  loadHomepage();
  loadCinemas();
})();
