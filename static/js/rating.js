(function () {
  'use strict';

  var csrfToken = document.querySelector('meta[name="csrf-token"]');
  csrfToken = csrfToken ? csrfToken.content : null;

  function buildStars(widget) {
    var current = parseInt(widget.dataset.current, 10) || 0;
    widget.innerHTML = '';
    for (var i = 1; i <= 10; i++) {
      var star = document.createElement('span');
      star.className = 'rating-star' + (i <= current ? ' filled' : '');
      star.textContent = '★';
      star.dataset.value = i;
      star.title = i + '/10';
      widget.appendChild(star);
    }
  }

  function paintStars(widget, upTo) {
    var stars = widget.querySelectorAll('.rating-star');
    stars.forEach(function (star) {
      var v = parseInt(star.dataset.value, 10);
      star.classList.toggle('filled', v <= upTo);
    });
  }

  function submitRating(widget, rating) {
    var type = widget.dataset.type;
    var traktId = widget.dataset.traktId;
    widget.classList.add('saving');
    fetch('/rate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({ type: type, trakt_id: traktId, rating: rating }),
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          return { ok: resp.ok, data: data };
        });
      })
      .then(function (result) {
        widget.classList.remove('saving');
        if (result.ok) {
          widget.dataset.current = rating;
          paintStars(widget, rating);
        } else {
          console.error('Rating failed:', result.data && result.data.error);
          paintStars(widget, parseInt(widget.dataset.current, 10) || 0);
        }
      })
      .catch(function (err) {
        widget.classList.remove('saving');
        console.error('Rating request failed:', err);
        paintStars(widget, parseInt(widget.dataset.current, 10) || 0);
      });
  }

  function initWidget(widget) {
    buildStars(widget);
    widget.addEventListener('mouseover', function (e) {
      if (!e.target.classList.contains('rating-star')) return;
      paintStars(widget, parseInt(e.target.dataset.value, 10));
    });
    widget.addEventListener('mouseleave', function () {
      paintStars(widget, parseInt(widget.dataset.current, 10) || 0);
    });
    widget.addEventListener('click', function (e) {
      if (!e.target.classList.contains('rating-star')) return;
      submitRating(widget, parseInt(e.target.dataset.value, 10));
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.rating-widget').forEach(initWidget);
  });
})();
