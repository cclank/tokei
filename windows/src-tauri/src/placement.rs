//! 快捷面板的纯几何计算，使用显示器工作区的物理像素。

#[derive(Clone, Copy)]
pub struct Bounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

#[derive(Debug)]
pub struct Placement {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

pub fn quick_placement(work: Bounds, scale: f64, tray: Option<Bounds>) -> Placement {
    let scale = if scale.is_finite() && scale > 0.0 {
        scale
    } else {
        1.0
    };
    let ww = work.width.max(1.0);
    let wh = work.height.max(1.0);
    let margin = (8.0 * scale).min(ww / 4.0).min(wh / 4.0);
    let width = (520.0 * scale).min(ww - 2.0 * margin);
    let height = (wh * 0.74)
        .min(680.0 * scale)
        .max(320.0 * scale)
        .min(wh - 2.0 * margin);
    let (center_x, top, bottom) = match tray {
        Some(tray) => (tray.x + tray.width / 2.0, tray.y, tray.y + tray.height),
        None => (work.x + ww - width / 2.0 - margin, work.y + wh, work.y + wh),
    };
    let x = (center_x - width / 2.0).clamp(work.x + margin, work.x + ww - width - margin);
    let y = if (top + bottom) / 2.0 > work.y + wh / 2.0 {
        top - height - margin
    } else {
        bottom + margin
    }
    .clamp(work.y + margin, work.y + wh - height - margin);
    Placement {
        x: x.round() as i32,
        y: y.round() as i32,
        width: width.round().max(1.0) as u32,
        height: height.round().max(1.0) as u32,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fits_scaled_and_negative_monitor_work_areas() {
        for scale in [1.0, 1.25, 1.5, 2.0] {
            for work in [
                Bounds {
                    x: 0.0,
                    y: 0.0,
                    width: 1920.0,
                    height: 1040.0,
                },
                Bounds {
                    x: -2560.0,
                    y: -200.0,
                    width: 2560.0,
                    height: 1400.0,
                },
                Bounds {
                    x: 100.0,
                    y: 40.0,
                    width: 400.0,
                    height: 260.0,
                },
            ] {
                for tray in [
                    None,
                    Some(Bounds {
                        x: work.x + 12.0,
                        y: work.y - 30.0,
                        width: 24.0,
                        height: 24.0,
                    }),
                    Some(Bounds {
                        x: work.x + work.width - 24.0,
                        y: work.y + work.height,
                        width: 24.0,
                        height: 24.0,
                    }),
                ] {
                    let p = quick_placement(work, scale, tray);
                    assert!(p.x as f64 >= work.x && p.y as f64 >= work.y);
                    assert!(p.x as f64 + p.width as f64 <= work.x + work.width + 1.0);
                    assert!(p.y as f64 + p.height as f64 <= work.y + work.height + 1.0);
                }
            }
        }
    }

    #[test]
    fn opens_below_top_tray_and_above_bottom_tray() {
        let work = Bounds {
            x: 0.0,
            y: 40.0,
            width: 1920.0,
            height: 1000.0,
        };
        let top = quick_placement(
            work,
            1.0,
            Some(Bounds {
                x: 1700.0,
                y: 10.0,
                width: 24.0,
                height: 24.0,
            }),
        );
        let bottom = quick_placement(
            work,
            1.0,
            Some(Bounds {
                x: 1700.0,
                y: 1040.0,
                width: 24.0,
                height: 24.0,
            }),
        );
        assert!(top.y >= 40);
        assert!(bottom.y + (bottom.height as i32) < 1040);
    }
}
