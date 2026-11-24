(function () {
  'use strict';

  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = meta ? meta.content : null;

  function saved(widget) {
    return parseInt(widget.dataset.current, 10) || 0;
  }

  // Each widget is a single keyboard stop (role=slider): arrows pick, Enter saves.
  function build(widget) {
    widget.setAttribute('role', 'slider');
    widget.setAttribute('tabindex', '0');
    widget.setAttribute('aria-label', 'Your rating for ' + (widget.dataset.title || 'this title'));
    widget.setAttribute('aria-valuemin', '0');
    widget.setAttribute('aria-valuemax', '10');
    widget.textContent = '';
    for (var i = 1; i <= 10; i++) {
      var star = document.createElement('span');
      star.className = 'rating-star';
      star.textContent = '★';
      star.dataset.value = i;
      widget.appendChild(star);
    }
    var value = document.createElement('span');
    value.className = 'rating-value';
    widget.appendChild(value);
    paint(widget, saved(widget));
  }

  function paint(widget, upTo) {
    widget.pending = upTo;
    widget.querySelectorAll('.rating-star').forEach(function (star) {
      star.classList.toggle('filled', parseInt(star.dataset.value, 10) <= upTo);
    });
    widget.querySelector('.rating-value').textContent = upTo || '';
    widget.setAttribute('aria-valuenow', upTo);
    widget.setAttribute('aria-valuetext', upTo ? upTo + ' out of 10' : 'Not rated');
  }

  function showError(widget, message) {
    var next = widget.nextElementSibling;
    if (next && next.classList.contains('rating-error')) next.remove();
    if (!message) return;
    var el = document.createElement('span');
    el.className = 'rating-error';
    el.setAttribute('role', 'alert');
    el.textContent = 'Rating not saved: ' + message;
    widget.after(el);
  }

  function submit(widget, rating) {
    if (rating < 1 || widget.classList.contains('saving')) return;
    widget.classList.add('saving');
    showError(widget, null);
    fetch('/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        type: widget.dataset.type,
        trakt_id: widget.dataset.traktId,
        rating: rating,
      }),
    })
      .then(function (resp) {
        return resp.json().then(function (data) {
          if (!resp.ok) throw new Error(data.error || 'Trakt did not accept it');
          widget.dataset.current = rating;
        });
      })
      .catch(function (err) {
        showError(widget, err.message);
      })
      .then(function () {
        widget.classList.remove('saving');
        paint(widget, saved(widget));
      });
  }

  function starValue(e) {
    return e.target.classList.contains('rating-star') ? parseInt(e.target.dataset.value, 10) : 0;
  }

  function init(widget) {
    build(widget);
    widget.addEventListener('mouseover', function (e) {
      if (starValue(e)) paint(widget, starValue(e));
    });
    widget.addEventListener('mouseleave', function () {
      if (!widget.classList.contains('saving')) paint(widget, saved(widget));
    });
    widget.addEventListener('blur', function () {
      if (!widget.classList.contains('saving')) paint(widget, saved(widget));
    });
    widget.addEventListener('click', function (e) {
      if (starValue(e)) submit(widget, starValue(e));
    });
    widget.addEventListener('keydown', function (e) {
      var step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
      if (step) {
        e.preventDefault();
        paint(widget, Math.min(10, Math.max(1, widget.pending + step)));
      } else if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        paint(widget, e.key === 'Home' ? 1 : 10);
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        submit(widget, widget.pending);
      }
    });
  }

  document.querySelectorAll('.rating-widget').forEach(init);
})();
