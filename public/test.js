/**
 * Chainlit Color Patcher - #fc5c02
 * Uses MutationObserver to catch dynamically rendered elements.
 * Works regardless of class name hashing or framework version.
 */

const ORANGE = '#fc5c02';

function patchColors() {
    // ── SEND / SUBMIT BUTTON ──────────────────────────────────
    // Strategy 1: look for button with a Send/Arrow SVG path near the textarea
    const textarea = document.querySelector('textarea');
    if (textarea) {
        // Walk up to the form/composer container
        let composer = textarea.closest('form') || textarea.parentElement;
        if (composer) {
            // Find all icon buttons inside the composer
            const buttons = composer.querySelectorAll('button');
            buttons.forEach(btn => {
                const svg = btn.querySelector('svg');
                if (svg) {
                    // The submit button is usually the last button or the one without text
                    btn.style.setProperty('color', ORANGE, 'important');
                    svg.style.setProperty('color', ORANGE, 'important');
                    // For path-based icons
                    svg.querySelectorAll('path, circle, rect, polyline, line').forEach(el => {
                        if (!el.getAttribute('fill') || el.getAttribute('fill') === 'none') {
                            el.style.setProperty('stroke', ORANGE, 'important');
                        } else {
                            el.style.setProperty('fill', ORANGE, 'important');
                        }
                    });
                }
            });
        }
    }

    // ── USER AVATAR ───────────────────────────────────────────
    // Strategy: find message containers, check for user role, style the avatar
    document.querySelectorAll('[data-author]').forEach(el => {
        const author = el.getAttribute('data-author');
        if (author && author.toLowerCase() === 'user') {
            const avatar = el.querySelector('[class*="avatar"], [class*="Avatar"], [class*="rounded-full"]');
            if (avatar) {
                avatar.style.setProperty('background-color', ORANGE, 'important');
            }
        }
    });

    // Also catch avatars that contain a user icon SVG (not a bot/robot icon)
    document.querySelectorAll('[class*="avatar"], [class*="Avatar"]').forEach(el => {
        const svg = el.querySelector('svg');
        if (svg) {
            // Heuristic: user avatars typically have a person/user icon
            svg.style.setProperty('color', ORANGE, 'important');
            svg.style.setProperty('fill', ORANGE, 'important');
        }
    });
}

// Run immediately
patchColors();

// Run whenever the DOM changes (catches React re-renders)
const observer = new MutationObserver(() => {
    patchColors();
});

observer.observe(document.body, {
    childList: true,
    subtree: true,
});

// Also run after short delays to catch late renders
setTimeout(patchColors, 500);
setTimeout(patchColors, 1500);
setTimeout(patchColors, 3000);