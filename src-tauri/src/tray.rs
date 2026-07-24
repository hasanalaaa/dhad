use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    App, AppHandle, Emitter, Manager, Runtime,
};

const MAIN_WINDOW_LABEL: &str = "main";
const MINI_WINDOW_LABEL: &str = "mini-assistant";

#[cfg(target_os = "macos")]
const QUICK_CHECK_LABEL: &str = "التدقيق السريع (Option+Space)";
#[cfg(not(target_os = "macos"))]
const QUICK_CHECK_LABEL: &str = "التدقيق السريع (Alt+Space)";

fn show_and_focus<R: Runtime>(app: &AppHandle<R>, label: &str) -> Result<(), String> {
    let window = app
        .get_webview_window(label)
        .ok_or_else(|| format!("window '{label}' is unavailable"))?;
    window.unminimize().map_err(|error| error.to_string())?;
    if label == MINI_WINDOW_LABEL {
        // Re-center on the active monitor before each invocation so the overlay
        // behaves consistently after display changes or virtual-desktop moves.
        let _ = window.center();
        let _ = window.set_always_on_top(true);
    }
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

pub fn show_main_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    show_and_focus(app, MAIN_WINDOW_LABEL)
}

pub fn hide_mini_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let window = app
        .get_webview_window(MINI_WINDOW_LABEL)
        .ok_or_else(|| "mini assistant window is unavailable".to_string())?;
    window.hide().map_err(|error| error.to_string())
}

pub fn toggle_mini_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let window = app
        .get_webview_window(MINI_WINDOW_LABEL)
        .ok_or_else(|| "mini assistant window is unavailable".to_string())?;

    if window.is_visible().map_err(|error| error.to_string())? {
        window.hide().map_err(|error| error.to_string())?;
        return Ok(());
    }

    show_and_focus(app, MINI_WINDOW_LABEL)?;
    let _ = window.emit("mini-assistant:activated", ());
    Ok(())
}

pub fn schedule_toggle_mini_window<R: Runtime>(app: &AppHandle<R>) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let _ = toggle_mini_window(&handle);
    });
}

fn schedule_show_main_window<R: Runtime>(app: &AppHandle<R>) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        let _ = show_main_window(&handle);
    });
}

pub fn create_system_tray<R: Runtime>(app: &App<R>) -> tauri::Result<()> {
    let open_item = MenuItem::with_id(app, "open", "افتح ضاد", true, None::<&str>)?;
    let quick_item = MenuItem::with_id(app, "quick-check", QUICK_CHECK_LABEL, true, None::<&str>)?;
    let settings_item = MenuItem::with_id(app, "settings", "الإعدادات", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "إنهاء", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_item, &quick_item, &settings_item, &quit_item])?;

    let mut builder = TrayIconBuilder::new()
        .tooltip("ضاد — مساعد الكتابة العربية")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => schedule_show_main_window(app),
            "quick-check" => schedule_toggle_mini_window(app),
            "settings" => {
                let handle = app.clone();
                let _ = app.run_on_main_thread(move || {
                    if show_main_window(&handle).is_ok() {
                        let _ = handle.emit_to(MAIN_WINDOW_LABEL, "desktop:open-settings", ());
                    }
                });
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                schedule_show_main_window(tray.app_handle());
            }
        });

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }

    builder.build(app)?;
    Ok(())
}

#[tauri::command]
pub fn toggle_mini_assistant(app: AppHandle) -> Result<(), String> {
    toggle_mini_window(&app)
}

#[tauri::command]
pub fn hide_mini_assistant(app: AppHandle) -> Result<(), String> {
    hide_mini_window(&app)
}

#[tauri::command]
pub fn open_main_window(app: AppHandle) -> Result<(), String> {
    show_main_window(&app)
}
