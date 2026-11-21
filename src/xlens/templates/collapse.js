// Expand-all / Collapse-all toggle for details elements
(function() {
  var btn = document.getElementById('toggle-all');
  if (!btn) return;

  btn.addEventListener('click', function() {
    var allDetails = document.querySelectorAll('details');
    var allOpen = true;

    allDetails.forEach(function(d) {
      if (!d.open) allOpen = false;
    });

    if (allOpen) {
      allDetails.forEach(function(d) { d.open = false; });
      btn.textContent = 'Expand All';
    } else {
      allDetails.forEach(function(d) { d.open = true; });
      btn.textContent = 'Collapse All';
    }
  });
})();
