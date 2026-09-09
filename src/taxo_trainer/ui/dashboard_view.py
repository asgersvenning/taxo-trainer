"""Analytics and confusion matrix dashboard view for taxo-trainer.

Renders user accuracy metrics, time-windowed stats, mastery breakdown, trouble taxa, and confusion matrix.
"""

from pathlib import Path

from nicegui import ui

from taxo_trainer.db import (
    APP_DB_PATH,
    USER_DB_PATH,
    get_active_data_source,
    get_db_connection,
)
from taxo_trainer.engine.analytics import (
    get_accuracy_over_time,
    get_confusion_matrix,
    get_dataset_coverage,
    get_global_stats,
    get_rank_mastery_stats,
    get_trouble_taxa,
)


def render_dashboard_view() -> None:
    """Render user analytics dashboard with time-range filtering, data source scope, and EMA chart."""
    app_conn = get_db_connection(APP_DB_PATH)
    user_conn = get_db_connection(USER_DB_PATH)

    selected_range = ["ALL"]
    selected_rank = ["FAMILY"]
    selected_limit = [5]
    selected_ema_window = [25]

    active_ds = get_active_data_source(app_conn)
    ds_display_name = (
        Path(active_ds).name
        if active_ds and active_ds != "default"
        else "Default Data Source"
    )

    container = ui.column().classes("w-full max-w-6xl mx-auto p-4 space-y-6 text-tt-main")

    with container:
        # Header & Time Filter Bar
        with ui.card().classes(
            "w-full bg-tt-raised p-4 rounded-lg shadow-md border border-tt-border space-y-3"
        ):
            with ui.row().classes("w-full justify-between items-center flex-wrap gap-3"):
                with ui.column().classes("gap-0"):
                    ui.label("Analytics & Mastery Dashboard").classes(
                        "text-2xl font-bold text-primary"
                    )
                    ui.label(
                        "Track your species identification progress, streaks, and taxonomic mastery over time."
                    ).classes("text-xs text-tt-muted")

                # Active Data Source Badge
                with ui.row().classes("items-center gap-2 bg-tt-surface px-3 py-1.5 rounded-lg border border-tt-warning"):
                    ui.icon("folder", color="warning").classes("text-sm")
                    ui.label("Active Data Source:").classes("text-xs font-bold text-tt-muted")
                    ui.label(ds_display_name).classes("text-xs font-mono font-bold text-tt-warning truncate max-w-[240px]")

            # Controls Bar: Time Range & Rank/Limit Selectors
            with (
                ui.row().classes("w-full justify-between items-center flex-wrap gap-3 pt-1 border-t border-tt-border"),
                ui.row().classes("items-center gap-1.5 bg-tt-surface p-1.5 rounded-lg border border-tt-border flex-wrap"),
            ):
                ui.label("Time Range:").classes("text-xs font-bold text-tt-muted mr-1")

                ranges = [
                    ("1H", "Past Hour"),
                    ("24H", "24 Hours"),
                    ("7D", "7 Days"),
                    ("30D", "30 Days"),
                    ("1Y", "Past Year"),
                    ("ALL", "All Time"),
                ]
                btn_widgets = {}

                def set_range(val: str) -> None:
                    selected_range[0] = val
                    for key, btn in btn_widgets.items():
                        if key == val:
                            btn.props("color=primary").classes("font-bold")
                        else:
                            btn.props("color=secondary").classes("font-normal")
                    refresh_dashboard()

                for key, label_text in ranges:
                    b = (
                        ui.button(
                            label_text,
                            on_click=lambda k=key: set_range(k),
                        )
                        .props(
                            "dense size=sm "
                            + ("color=primary" if key == "ALL" else "color=secondary")
                        )
                        .classes("text-xs px-2.5")
                    )
                    btn_widgets[key] = b


        # Dynamic Content Container
        content_container = ui.column().classes("w-full space-y-6")

        def refresh_dashboard() -> None:
            content_container.clear()
            r_val = selected_range[0]
            rank_val = selected_rank[0]
            limit_val = selected_limit[0]
            win_val = selected_ema_window[0]
            active_ds_current = get_active_data_source(app_conn)

            stats = get_global_stats(user_conn, app_conn, time_range=r_val, data_source=active_ds_current)
            coverage = get_dataset_coverage(user_conn, app_conn, data_source=active_ds_current)
            best_ranks, worst_ranks = get_rank_mastery_stats(
                user_conn, app_conn, rank_level=rank_val, time_range=r_val, data_source=active_ds_current, limit=limit_val
            )
            trouble_taxa = get_trouble_taxa(
                user_conn, app_conn, time_range=r_val, limit=5, data_source=active_ds_current
            )
            confusion = get_confusion_matrix(
                user_conn, app_conn, time_range=r_val, limit=10, data_source=active_ds_current
            )
            ema_points = get_accuracy_over_time(
                user_conn, app_conn, time_range=r_val, data_source=active_ds_current, window_size=win_val
            )

            with content_container:
                # 1. Summary Metrics Cards Grid (4 Cards)
                with ui.row().classes("w-full gap-4 justify-between flex-wrap"):
                    with ui.card().classes(
                        "flex-1 min-w-[200px] bg-tt-raised p-4 rounded-lg shadow-md border-l-4 border-tt-primary text-center"
                    ):
                        ui.label("Total Attempts").classes(
                            "text-xs text-tt-muted font-semibold uppercase"
                        )
                        ui.label(str(stats["total_attempts"])).classes(
                            "text-3xl font-bold mt-1 text-tt-main"
                        )
                        ui.label(f"Filter: {r_val}").classes(
                            "text-xs text-tt-muted mt-1"
                        )

                    with ui.card().classes(
                        "flex-1 min-w-[200px] bg-tt-raised p-4 rounded-lg shadow-md border-l-4 border-tt-positive text-center"
                    ):
                        ui.label("Unassisted Accuracy").classes(
                            "text-xs text-tt-muted font-semibold uppercase"
                        )
                        ui.label(f"{stats['unassisted_accuracy_pct']}%").classes(
                            "text-3xl font-bold mt-1 text-tt-positive"
                        )
                        ui.label(
                            f"({stats['unassisted_correct']} / {stats['unassisted_attempts']} unassisted)"
                        ).classes("text-xs text-tt-muted mt-1")

                    with ui.card().classes(
                        "flex-1 min-w-[200px] bg-tt-raised p-4 rounded-lg shadow-md border-l-4 border-tt-warning text-center"
                    ):
                        ui.label("Active / Best Streak").classes(
                            "text-xs text-tt-muted font-semibold uppercase"
                        )
                        with ui.row().classes("justify-center items-center gap-2 mt-1"):
                            ui.label(f"🔥 {stats['current_streak']}").classes(
                                "text-2xl font-bold text-tt-warning"
                            )
                            ui.label("|").classes("text-tt-muted")
                            ui.label(f"🏆 {stats['best_streak']}").classes(
                                "text-2xl font-bold text-tt-warning"
                            )
                        ui.label("Active source record").classes(
                            "text-xs text-tt-muted mt-1"
                        )

                    with ui.card().classes(
                        "flex-1 min-w-[200px] bg-tt-raised p-4 rounded-lg shadow-md border-l-4 border-tt-primary text-center"
                    ):
                        ui.label("Mastered Species").classes(
                            "text-xs text-tt-muted font-semibold uppercase"
                        )
                        ui.label(str(stats["mastered_species_count"])).classes(
                            "text-3xl font-bold mt-1 text-tt-primary"
                        )
                        ui.label("≥90% accuracy over ≥5 attempts").classes(
                            "text-xs text-tt-muted mt-1"
                        )

                # 2. Accuracy Over Time ECharts Display (with Window Selector & Interactive Zoom)
                with ui.card().classes(
                    "w-full bg-tt-raised p-5 rounded-lg shadow-md border border-tt-border space-y-3"
                ):
                    with ui.row().classes("w-full justify-between items-center flex-wrap gap-2"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("show_chart", color="primary").classes("text-base")
                            ui.label("Accuracy Over Time").classes(
                                "text-sm font-bold text-tt-primary"
                            )
                            if ema_points:
                                latest_ema = ema_points[-1].ema_accuracy
                                ui.label(f"Current EMA: {latest_ema}%").classes("text-xs font-bold text-tt-positive ml-2")

                        # Window Size Controls
                        with ui.row().classes("items-center gap-2"):
                            ui.label("Smoothing Window:").classes("text-xs text-tt-muted font-medium")
                            window_options = {
                                10: "10 Attempts",
                                25: "25 Attempts",
                                50: "50 Attempts",
                                100: "100 Attempts",
                            }
                            win_select = (
                                ui.select(
                                    options=window_options,
                                    value=win_val,
                                )
                                .props("dense outlined ")
                                .classes("w-32 text-xs text-tt-main")
                            )

                            def update_win(val: int) -> None:
                                selected_ema_window[0] = val
                                refresh_dashboard()

                            win_select.on_value_change(lambda e: update_win(e.value))

                    ui.label(
                        f"Exponential moving average (EMA, {win_val}-attempt window) of unassisted identification accuracy over time."
                    ).classes("text-xs text-tt-muted mb-1")

                    if not ema_points:
                        ui.label("No attempt history recorded for this data source yet.").classes(
                            "text-xs text-tt-muted italic py-6 text-center w-full"
                        )
                    else:
                        x_labels = [p.timestamp for p in ema_points]
                        y_values = [p.ema_accuracy for p in ema_points]
                        avg_acc = stats["unassisted_accuracy_pct"]

                        chart_options = {
                            "tooltip": {
                                "trigger": "axis",
                                "formatter": "Time: {b}<br/>Accuracy: {c}%",
                                "backgroundColor": "var(--tt-surface)",
                                "borderColor": "var(--tt-border)",
                                "textStyle": {"color": "var(--tt-main)", "fontSize": 12},
                            },
                            "grid": {
                                "left": "3%",
                                "right": "4%",
                                "bottom": "14%",
                                "top": "12%",
                                "containLabel": True,
                            },
                            "dataZoom": [
                                {
                                    "type": "inside",
                                    "start": max(0, 100 - int(100 * 100 / max(1, len(ema_points)))),
                                    "end": 100,
                                },
                                {
                                    "type": "slider",
                                    "height": 18,
                                    "bottom": "0%",
                                    "borderColor": "var(--tt-border)",
                                    "fillerColor": "var(--tt-primary-soft)",
                                    "handleStyle": {"color": "var(--tt-primary)"},
                                    "textStyle": {"color": "var(--tt-muted)", "fontSize": 10},
                                },
                            ],
                            "xAxis": {
                                "type": "category",
                                "boundaryGap": False,
                                "data": x_labels,
                                "axisLabel": {"color": "var(--tt-muted)", "fontSize": 10},
                                "axisLine": {"lineStyle": {"color": "var(--tt-border)"}},
                            },
                            "yAxis": {
                                "type": "value",
                                "min": 0,
                                "max": 100,
                                "interval": 20,
                                "axisLabel": {"formatter": "{value}%", "color": "var(--tt-muted)", "fontSize": 10},
                                "splitLine": {"lineStyle": {"color": "var(--tt-border)"}},
                            },
                            "series": [
                                {
                                    "name": "EMA Accuracy",
                                    "type": "line",
                                    "smooth": True,
                                    "symbol": "none",
                                    "lineStyle": {"color": "var(--tt-primary)", "width": 2.5},
                                    "data": y_values,
                                    "markLine": {
                                        "silent": True,
                                        "symbol": "none",
                                        "label": {
                                            "formatter": f"Avg ({avg_acc}%)",
                                            "position": "insideEndTop",
                                            "color": "var(--tt-positive)",
                                            "fontSize": 10,
                                        },
                                        "lineStyle": {"color": "var(--tt-positive)", "type": "dashed", "width": 1.5},
                                        "data": [{"yAxis": avg_acc}],
                                    },
                                    "markPoint": {
                                        "symbolSize": 32,
                                        "label": {"fontSize": 9, "color": "#ffffff"},
                                        "data": [
                                            {"type": "max", "name": "Peak", "itemStyle": {"color": "var(--q-positive)"}},
                                            {"type": "min", "name": "Trough", "itemStyle": {"color": "var(--q-negative)"}},
                                        ],
                                    },
                                    "areaStyle": {"color": "var(--tt-primary)", "opacity": 0.12},
                                }
                            ],
                        }
                        ui.echart(chart_options, renderer="svg").classes("w-full h-56")

                # 3. Dataset Species Coverage Meter
                with ui.card().classes(
                    "w-full bg-tt-raised p-4 rounded-lg shadow-md border border-tt-border"
                ):
                    with ui.row().classes("w-full justify-between items-center mb-1"):
                        ui.label("Dataset Species Coverage").classes(
                            "text-xs font-bold text-tt-main uppercase tracking-wider"
                        )
                        ui.label(
                            f"{coverage['encountered_species']} / {coverage['total_species']} species encountered ({coverage['coverage_pct']}%)"
                        ).classes("text-xs font-bold text-tt-primary")
                    ui.linear_progress(
                        value=coverage["coverage_pct"] / 100.0, show_value=False
                    ).props("color=primary stripe rounded").classes("h-2.5 w-full")

                # 4. Taxonomic Mastery Breakdown Grid (Multi-Rank & Bayesian Score)
                rank_plural_map = {
                    "ORDER": "Orders",
                    "FAMILY": "Families",
                    "GENUS": "Genera",
                    "SPECIES": "Species",
                }
                curr_rank_plural = rank_plural_map.get(rank_val, "Families")

                with ui.column().classes("w-full space-y-3"):
                    # Rank and Limit Selector Toolbar
                    with ui.row().classes(
                        "w-full justify-between items-center bg-tt-raised p-3 rounded-lg border border-tt-border flex-wrap gap-3"
                    ):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("layers", color="warning").classes("text-base")
                            ui.label("Taxonomic Rank Analysis:").classes("text-xs font-bold text-tt-main")

                            rank_options = {
                                "ORDER": "Order",
                                "FAMILY": "Family",
                                "GENUS": "Genus",
                                "SPECIES": "Species",
                            }
                            rank_select = (
                                ui.select(
                                    options=rank_options,
                                    value=rank_val,
                                )
                                .props("dense outlined ")
                                .classes("w-32 text-xs text-tt-main")
                            )

                            def update_rank(val: str) -> None:
                                selected_rank[0] = val
                                refresh_dashboard()

                            rank_select.on_value_change(lambda e: update_rank(e.value))

                        with ui.row().classes("items-center gap-2"):
                            ui.label("Items to Show:").classes("text-xs font-bold text-tt-main")
                            limit_options = {
                                5: "Top 5",
                                10: "Top 10",
                                20: "Top 20",
                                0: "Show All",
                            }
                            limit_select = (
                                ui.select(
                                    options=limit_options,
                                    value=limit_val,
                                )
                                .props("dense outlined ")
                                .classes("w-28 text-xs text-tt-main")
                            )

                            def update_limit(val: int) -> None:
                                selected_limit[0] = val
                                refresh_dashboard()

                            limit_select.on_value_change(lambda e: update_limit(e.value))

                    with ui.row().classes("w-full gap-4 justify-between flex-wrap items-start"):
                        # Best Performing Taxa
                        with ui.card().classes(
                            "flex-1 min-w-[320px] bg-tt-raised p-4 rounded-lg shadow-md border border-tt-border space-y-2 max-h-96 overflow-y-auto"
                        ):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("verified", color="positive").classes("text-base")
                                ui.label(f"Top Mastered {curr_rank_plural}").classes(
                                    "text-sm font-bold text-tt-positive"
                                )
                            ui.label("Ranked by Bayesian accuracy under 50% prior").classes("text-xs text-tt-muted")

                            if not best_ranks:
                                ui.label(f"No {curr_rank_plural.lower()} attempts recorded yet.").classes(
                                    "text-xs text-tt-muted italic py-2"
                                )
                            else:
                                with ui.column().classes("w-full gap-1.5"):
                                    for item in best_ranks:
                                        with ui.row().classes(
                                            "w-full justify-between items-center bg-tt-surface px-3 py-1.5 rounded border border-tt-border"
                                        ):
                                            ui.label(item.display_name).classes(
                                                "text-xs font-medium text-tt-main truncate max-w-[200px]"
                                            )
                                            ui.label(
                                                f"{item.accuracy_pct}% ({item.correct_attempts}/{item.total_attempts})"
                                            ).classes("text-xs font-bold text-tt-positive")

                        # Struggling Taxa (Needing Practice)
                        with ui.card().classes(
                            "flex-1 min-w-[320px] bg-tt-raised p-4 rounded-lg shadow-md border border-tt-border space-y-2 max-h-96 overflow-y-auto"
                        ):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("warning", color="warning").classes("text-base")
                                ui.label(f"{curr_rank_plural} Needing Practice").classes(
                                    "text-sm font-bold text-tt-warning"
                                )
                            ui.label("Ranked by Bayesian accuracy under 50% prior").classes("text-xs text-tt-muted")

                            if not worst_ranks:
                                ui.label("No weak patterns identified yet!").classes(
                                    "text-xs text-tt-muted italic py-2"
                                )
                            else:
                                with ui.column().classes("w-full gap-1.5"):
                                    for item in worst_ranks:
                                        with ui.row().classes(
                                            "w-full justify-between items-center bg-tt-surface px-3 py-1.5 rounded border border-tt-border"
                                        ):
                                            ui.label(item.display_name).classes(
                                                "text-xs font-medium text-tt-main truncate max-w-[200px]"
                                            )
                                            ui.label(
                                                f"{item.accuracy_pct}% ({item.correct_attempts}/{item.total_attempts})"
                                            ).classes("text-xs font-bold text-tt-warning")

                # 5. Trouble Taxa List Card
                if trouble_taxa:
                    with ui.card().classes(
                        "w-full bg-tt-raised p-4 rounded-lg shadow-md border border-tt-border space-y-2"
                    ):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("priority_high", color="negative").classes(
                                "text-base"
                            )
                            ui.label("Trouble Taxa (Lowest Accuracy Species)").classes(
                                "text-sm font-bold text-tt-negative"
                            )

                        t_columns = [
                            {
                                "name": "species",
                                "label": "Species",
                                "field": "display_name",
                                "align": "left",
                            },
                            {
                                "name": "canonical",
                                "label": "Scientific Name",
                                "field": "canonical_name",
                                "align": "left",
                            },
                            {
                                "name": "family",
                                "label": "Family",
                                "field": "family",
                                "align": "left",
                            },
                            {
                                "name": "accuracy",
                                "label": "Accuracy",
                                "field": "acc_str",
                                "align": "center",
                            },
                        ]
                        t_rows = [
                            {
                                "display_name": tt.display_name,
                                "canonical_name": tt.canonical_name,
                                "family": tt.family,
                                "acc_str": f"{tt.accuracy_pct}% ({tt.correct_attempts}/{tt.total_attempts})",
                            }
                            for tt in trouble_taxa
                        ]
                        ui.table(
                            columns=t_columns, rows=t_rows, row_key="canonical_name"
                        ).classes("w-full bg-tt-surface text-tt-main rounded-md").props(
                            "flat bordered dense"
                        )

                # 6. Pairwise Lookalikes (Confusion Matrix) Table Card
                with ui.card().classes(
                    "w-full bg-tt-raised p-5 rounded-lg shadow-md border border-tt-border space-y-2"
                ):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("compare_arrows", color="warning").classes(
                            "text-base"
                        )
                        ui.label("Top Taxonomic Lookalikes (Confusion Matrix)").classes(
                            "text-sm font-bold text-tt-warning"
                        )
                    ui.label(
                        "Pairwise misidentifications logged during quiz attempts."
                    ).classes("text-xs text-tt-muted mb-2")

                    if not confusion:
                        ui.label(
                            "No misidentifications recorded in this time period. Keep practicing!"
                        ).classes(
                            "text-xs text-tt-muted italic py-4 text-center w-full"
                        )
                    else:
                        columns = [
                            {
                                "name": "target",
                                "label": "Target Species",
                                "field": "target_display",
                                "align": "left",
                            },
                            {
                                "name": "target_sci",
                                "label": "Scientific Name",
                                "field": "target_canonical",
                                "align": "left",
                            },
                            {
                                "name": "guessed",
                                "label": "Mistaken For",
                                "field": "guessed_display",
                                "align": "left",
                            },
                            {
                                "name": "guessed_sci",
                                "label": "Guessed Scientific",
                                "field": "guessed_canonical",
                                "align": "left",
                            },
                            {
                                "name": "count",
                                "label": "Frequency",
                                "field": "count",
                                "align": "center",
                            },
                        ]
                        rows = [
                            {
                                "target_display": c.target_display,
                                "target_canonical": c.target_canonical,
                                "guessed_display": c.guessed_display,
                                "guessed_canonical": c.guessed_canonical,
                                "count": f"{c.count} time(s)",
                            }
                            for c in confusion
                        ]
                        ui.table(
                            columns=columns, rows=rows, row_key="target_canonical"
                        ).classes("w-full bg-tt-surface text-tt-main rounded-md").props(
                            "flat bordered dense"
                        )

        # Initial dashboard load
        refresh_dashboard()
