window.addEventListener(
    'beforeunload', () => {
        document.querySelector("#shutdown_button").click()
    }
);
