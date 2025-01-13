document.addEventListener('DOMContentLoaded', function () {
    const gifs = document.querySelectorAll('.type-card-img'); // Select all GIF images

    gifs.forEach(gif => {
        const gifSrc = gif.src; // Get the source of the GIF
        
        // Pause the GIF initially by replacing it with a static image (e.g., first frame of the GIF)
        gif.src = gifSrc.replace('.gif', '_static.png'); // You need a static image, replace _static.jpg with your image

        gif.addEventListener('mouseenter', function () {
            gif.src = gifSrc; // Revert to the animated GIF on hover
        });

        gif.addEventListener('mouseleave', function () {
            gif.src = gifSrc.replace('.gif', '_static.png'); // Replace with static image again when mouse leaves
        });
    });
});
