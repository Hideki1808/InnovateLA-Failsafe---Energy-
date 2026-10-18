"""
map_gestures.py - mouse and trackpad gestures for the map.

What it does:
  - Mouse wheel                          -> the map ZOOMS in and out.
  - Two fingers sliding on the trackpad  -> the map MOVES (pans) with your fingers.
  - Pinching two fingers in or out       -> the map ZOOMS.

Why it needs a little JavaScript: browsers report a two-finger slide, a pinch and a
mouse wheel all as "wheel" events, and the map library zooms on every one of them. The
script below tells them apart:
  - a pinch has the Ctrl key flag set                      -> let the map zoom
  - a mouse wheel moves in whole "notches": counted in lines, or in big round steps
    (like 100 pixels) straight up or down                  -> let the map zoom
  - anything else (small or sideways steps) is a trackpad slide -> move the map instead
(A guess: a few "free-spinning" mouse wheels send small steps and will pan instead.)

It runs in the page once (a hidden helper frame installs it on the dashboard).
"""

import streamlit as st

_SCRIPT = """
<script>
(function () {
  const page = window.parent;                 // the dashboard page around this helper frame
  if (page.__mapGestures2) return;            // install only once
  page.__mapGestures2 = true;

  // Find the map object (deck.gl) behind a map canvas, through React's internals.
  function findDeck(canvas) {
    const key = Object.keys(canvas).find(k => k.startsWith("__reactFiber"));
    let fiber = key && canvas[key];
    for (let depth = 0; fiber && depth < 40; depth++, fiber = fiber.return) {
      let hook = fiber.memoizedState;
      for (let i = 0; hook && i < 30; i++, hook = hook.next) {
        const deck = hook.memoizedState && hook.memoizedState.current && hook.memoizedState.current.deck;
        if (deck && typeof deck.setProps === "function" && deck.viewManager) return deck;
      }
    }
    return null;
  }

  page.document.addEventListener("wheel", function (e) {
    const wrapper = e.target.closest && e.target.closest("#deckgl-wrapper");
    if (!wrapper) return;                      // not over the map
    if (e.ctrlKey) return;                     // a pinch: let the map zoom as usual
    const wheelNotch = e.deltaMode !== 0 ||   // counted in lines or pages: a mouse wheel
      (e.deltaX === 0 && Math.abs(e.deltaY) >= 40 && Number.isInteger(e.deltaY));
    if (wheelNotch) return;                    // a mouse wheel: let the map zoom as usual
    const canvas = wrapper.querySelector("canvas#deckgl-overlay");
    if (!canvas) return;

    // A two-finger slide: don't zoom, move the map instead
    e.preventDefault();
    e.stopPropagation();
    const deck = findDeck(canvas);
    if (!deck) return;
    const viewport = deck.getViewports()[0];
    if (!viewport) return;
    const dx = e.deltaX, dy = e.deltaY;
    // The spot that should end up in the middle of the map, after moving by (dx, dy)
    const [longitude, latitude] = viewport.unproject([viewport.width / 2 + dx, viewport.height / 2 + dy]);
    const viewState = Object.assign({}, deck.viewManager.getViewState(viewport.id), {longitude, latitude});
    // Tell the map its view changed, the same way a mouse drag would
    deck._onViewStateChange({viewId: viewport.id, viewState, interactionState: {isPanning: true}});
  }, {capture: true, passive: false});
})();
</script>
"""


def install():
    """Add the gesture script to the page. Its little frame is hidden (style.py hides the
    container with key "gesture_helper"); a hidden frame still runs its script."""
    with st.container(key="gesture_helper"):
        st.iframe(_SCRIPT, height=1)
