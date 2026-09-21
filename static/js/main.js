document.addEventListener('click', e => { if(e.target.matches('[data-confirm]') && !confirm(e.target.dataset.confirm)) e.preventDefault(); });
