// Table sorting for columns with class="sortable"
(function() {
  var headers = document.querySelectorAll('th.sortable');

  headers.forEach(function(th) {
    th.addEventListener('click', function() {
      var table = th.closest('table');
      var tbody = table.querySelector('tbody');
      var colIndex = Array.prototype.indexOf.call(th.parentNode.children, th);
      var currentDir = th.getAttribute('data-sort-dir') || 'none';
      var newDir = (currentDir === 'asc') ? 'desc' : 'asc';

      // Reset sibling headers
      var siblings = th.parentNode.querySelectorAll('th.sortable');
      siblings.forEach(function(s) {
        s.classList.remove('sort-asc', 'sort-desc');
        s.setAttribute('data-sort-dir', 'none');
      });

      // Apply new sort direction
      th.setAttribute('data-sort-dir', newDir);
      th.classList.add(newDir === 'asc' ? 'sort-asc' : 'sort-desc');

      // Get rows and sort
      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
      rows.sort(function(a, b) {
        var aText = a.children[colIndex] ? a.children[colIndex].textContent.trim() : '';
        var bText = b.children[colIndex] ? b.children[colIndex].textContent.trim() : '';

        // Try numeric comparison
        var aNum = parseFloat(aText.replace(/[$,%x]/g, ''));
        var bNum = parseFloat(bText.replace(/[$,%x]/g, ''));

        var result;
        if (!isNaN(aNum) && !isNaN(bNum)) {
          result = aNum - bNum;
        } else {
          result = aText.localeCompare(bText);
        }

        return newDir === 'desc' ? -result : result;
      });

      // Re-append sorted rows
      rows.forEach(function(row) {
        tbody.appendChild(row);
      });
    });
  });
})();
