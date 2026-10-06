export function initSubmenu() {
    const menuItems = document.querySelectorAll('.menu-item');
    menuItems.forEach(item => {
        const link = item.querySelector('.menu-link');
        link.addEventListener('mouseenter', () => {
            document.querySelectorAll('.menu-item').forEach(i => {
                i.classList.remove('active');
            });
            item.classList.add('active');
        });
    });
}

export function menuManager(menuContainer, menuContents) { 
    let hideTimeout = null;
    menuContainer.innerHTML = menuContents;
    if (menuContainer) {
        menuContainer.addEventListener('mouseenter', () => {
            menuContainer.style.display = 'flex';
            if (hideTimeout) { clearTimeout(hideTimeout); hideTimeout = null; }
        });
        menuContainer.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                menuContainer.style.display = 'none';
                const activeItems = menuContainer.querySelectorAll('.menu-item.active');
                activeItems.forEach(item => item.classList.remove('active'));
            }, 500);
        });
    };
    initSubmenu();
}
