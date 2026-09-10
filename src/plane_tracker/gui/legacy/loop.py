def finish_frame(max_frames):
        global frames_rendered

        pygame.display.update()
        frames_rendered += 1
        if max_frames is not None and frames_rendered >= max_frames:
            return True
        time.sleep(0.05)
        return False

def run(mode="preview", stats_uploader=None, _max_frames=None):

    if mode not in {"preview", "production"}:
        raise ValueError("mode must be 'preview' or 'production'")
    if mode == "production" and not callable(stats_uploader):
        raise ValueError("production mode requires a stats_uploader callback")

    app.runtime_mode = mode
    app._stats_uploader = stats_uploader
    app.tracker_running = True
    if mode == "preview":
        app.offline = True
        app.window = _create_window()
        app.initialise_preview_state()
    else:
        app.load_icao_cache()
        app.acquire_instance_lock()
        app.start_background_services()

    render = FunctionType(_main_impl.__code__, vars(app), "main", _main_impl.__defaults__)
    render(max_frames=_max_frames)


if __name__ == "__main__":
    run(mode="preview")
