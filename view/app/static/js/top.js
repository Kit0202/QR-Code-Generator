
    // Get the back-to-top button element
    const backToTopButton = document.querySelector('.back-to-top');

    // Add a scroll event listener to the window
    window.addEventListener('scroll', () => {
        // Show the button if the user has scrolled down 200px or more
        if (window.scrollY > 1300) {
            backToTopButton.style.display = 'flex'; // Make the button visible
        } else {
            backToTopButton.style.display = 'none'; // Hide the button
        }
    });

    // Smooth scroll to the top when the button is clicked
    backToTopButton.addEventListener('click', () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

