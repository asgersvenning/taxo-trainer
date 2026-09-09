"""Analytics and confusion matrix dashboard view for taxo-trainer.

Renders user accuracy metrics, time-windowed stats, mastery breakdown, trouble taxa, and confusion matrix.
"""

import json
from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from taxo_trainer.db import (
    APP_DB_PATH,
    USER_DB_PATH,
    get_active_data_source,
    get_app_metadata,
    get_db_connection,
)
from taxo_trainer.engine.analytics import (
    get_accuracy_over_time,
    get_confusion_matrix,
    get_dataset_coverage,
    get_global_stats,
    get_rank_mastery_stats,
)


def render_dashboard_view(on_practise: Callable[[list[str]], None] | None = None) -> Callable[[], None]:
    """Render user analytics dashboard with time-range filtering, data source scope, and EMA chart."""
    app_conn = get_db_connection(APP_DB_PATH)
    user_conn = get_db_connection(USER_DB_PATH)

    def add_practice_action(table) -> None:
        if on_practise is None:
            return
        table.columns.append({"name": "practice", "label": "", "field": "taxon_keys", "align": "right"})
        table.add_slot("body-cell-practice", """
            <q-td :props="props">
                <q-btn flat dense label="Practise" color="primary"
                    :aria-label="'Practise ' + (props.row.display_name || props.row.target_display + ' / ' + props.row.guessed_display)"
                    @click="$parent.$emit('practise', props.row.taxon_keys)" />
            </q-td>
        """)
        table.on("practise", lambda e: on_practise([str(key) for key in e.args]))
        table.update()

    selected_range = ["ALL"]
    selected_rank = ["SPECIES"]
    selected_ema_window = [25]
    table_pagination = {"rowsPerPage": 5, "page": 1, "sortBy": "accuracy", "descending": False}

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
                    table_pagination["page"] = 1
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
            win_val = selected_ema_window[0]
            active_ds_current = get_active_data_source(app_conn)
            language = get_app_metadata("language_preference", "da", conn=app_conn)

            stats = get_global_stats(user_conn, app_conn, time_range=r_val, data_source=active_ds_current)
            coverage = get_dataset_coverage(user_conn, app_conn, data_source=active_ds_current)
            _, ranked_taxa = get_rank_mastery_stats(
                user_conn, app_conn, rank_level=rank_val, time_range=r_val, data_source=active_ds_current, limit=0, language=language
            )
            confusion = get_confusion_matrix(
                user_conn, app_conn, time_range=r_val, limit=10, data_source=active_ds_current, language=language
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
                        ui.label(f"{stats['total_attempts'] - stats['unassisted_attempts']} assisted").classes(
                            "text-xs text-tt-muted mt-1"
                        )

                    with ui.card().classes(
                        "flex-1 min-w-[200px] bg-tt-raised p-4 rounded-lg shadow-md border-l-4 border-tt-positive text-center"
                    ):
                        ui.label("Unassisted Accuracy").classes(
                            "text-xs text-tt-muted font-semibold uppercase"
                        )
                        ui.label(f"{stats['unassisted_accuracy_pct']}%" if stats["unassisted_attempts"] else "—").classes(
                            "text-3xl font-bold mt-1 text-tt-positive"
                        )
                        ui.label(
                            f"{stats['unassisted_correct']} correct / {stats['unassisted_attempts']} unassisted"
                            if stats["unassisted_attempts"] else "No unassisted attempts in this period"
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
                        ui.label("All time · current dataset").classes(
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
                        ui.label("≥90% over ≥5 unassisted attempts").classes(
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
                                ui.label(f"Recent trend: {latest_ema}%").classes("text-xs font-bold text-tt-main ml-2")

                        # Window Size Controls
                        with ui.row().classes("items-center gap-2"):
                            ui.label("Trend smoothing:").classes("text-xs text-tt-muted font-medium")
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
                        "Unassisted accuracy: the line shows the smoothed trend; the dashed line shows the period average."
                    ).classes("text-xs text-tt-muted mb-1")

                    if not ema_points:
                        ui.label("No unassisted attempts in this period. Try a quiz question without hints.").classes(
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
                                    "textStyle": {"color": "var(--tt-muted)", "fontSize": 12},
                                },
                            ],
                            "xAxis": {
                                "type": "category",
                                "boundaryGap": False,
                                "data": x_labels,
                                "axisLabel": {"color": "var(--tt-muted)", "fontSize": 12},
                                "axisLine": {"lineStyle": {"color": "var(--tt-border)"}},
                            },
                            "yAxis": {
                                "type": "value",
                                "min": 0,
                                "max": 100,
                                "interval": 20,
                                "axisLabel": {"formatter": "{value}%", "color": "var(--tt-muted)", "fontSize": 12},
                                "splitLine": {"lineStyle": {"color": "var(--tt-border)"}},
                            },
                            "series": [
                                {
                                    "name": "Unassisted accuracy",
                                    "type": "line",
                                    "smooth": True,
                                    "symbol": "none",
                                    "lineStyle": {"color": "var(--tt-primary)", "width": 2.5},
                                    "data": y_values,
                                    "markLine": {
                                        "silent": True,
                                        "symbol": "none",
                                        "label": {
                                            "formatter": f"Period average ({avg_acc}%)",
                                            "position": "insideEndTop",
                                            "color": "var(--tt-positive)",
                                            "fontSize": 12,
                                        },
                                        "lineStyle": {"color": "var(--tt-positive)", "type": "dashed", "width": 1.5},
                                        "data": [{"yAxis": avg_acc}],
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
                        ui.label("Species encountered · all time").classes(
                            "text-xs font-bold text-tt-main uppercase tracking-wider"
                        )
                        ui.label(
                            f"{coverage['encountered_species']} / {coverage['total_species']} species encountered ({coverage['coverage_pct']}%)"
                        ).classes("text-xs font-bold text-tt-primary")
                    ui.linear_progress(
                        value=coverage["coverage_pct"] / 100.0, show_value=False
                    ).props("color=primary stripe rounded").classes("h-2.5 w-full")

                # One sortable table replaces overlapping best/worst and trouble lists.
                with ui.card().classes("w-full bg-tt-raised p-4 rounded-lg border border-tt-border gap-3"):
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.label("Accuracy by group").classes("text-sm font-bold text-tt-main")
                        rank_select = ui.select(
                            options={"ORDER": "Order", "FAMILY": "Family", "GENUS": "Genus", "SPECIES": "Species"},
                            value=rank_val,
                            label="Group by",
                        ).props("dense outlined").classes("w-40")

                        def update_rank(value: str) -> None:
                            selected_rank[0] = value
                            table_pagination["page"] = 1
                            refresh_dashboard()

                        rank_select.on_value_change(lambda e: update_rank(e.value))
                    ui.label("Practice order balances accuracy with the number of attempts. Click accuracy to reverse the order.").classes("text-xs text-tt-muted")
                    if not ranked_taxa:
                        ui.label("No unassisted results with this group information in this period.").classes("text-sm text-tt-muted")
                    else:
                        columns = [
                            {"name": "name", "label": "Taxon", "field": "display_name", "align": "left", "sortable": True},
                            {"name": "accuracy", "label": "Unassisted accuracy", "field": "accuracy", "align": "right", "sortable": True, ":format": "value => `${value}%`",
                             ":sort": "(a, b, rowA, rowB) => rowA.bayesian_score - rowB.bayesian_score"},
                            {"name": "attempts", "label": "Attempts", "field": "attempts", "align": "right", "sortable": True},
                        ]
                        rows = [{"taxon_key": item.taxon_key, "taxon_keys": [str(item.taxon_key)], "display_name": item.display_name, "accuracy": item.accuracy_pct, "bayesian_score": item.bayesian_score, "attempts": item.total_attempts} for item in ranked_taxa]
                        group_table = ui.table(columns=columns, rows=rows, row_key="taxon_key", pagination=table_pagination.copy(), on_pagination_change=lambda e: table_pagination.update(e.value)).classes("w-full bg-tt-surface text-tt-main").props("flat bordered dense binary-state-sort")

                        add_practice_action(group_table)

                # 6. Pairwise Lookalikes (Confusion Matrix) Table Card
                with ui.card().classes(
                    "w-full bg-tt-raised p-5 rounded-lg shadow-md border border-tt-border space-y-2"
                ):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("compare_arrows", color="warning").classes(
                            "text-base"
                        )
                        ui.label("Frequently confused taxa").classes(
                            "text-sm font-bold text-tt-warning"
                        )
                    ui.label(
                        "Mistaken taxon pairs in this period, including assisted attempts."
                    ).classes("text-xs text-tt-muted mb-2")

                    if not confusion:
                        ui.label(
                            "No mistaken taxon pairs recorded in this period."
                        ).classes(
                            "text-xs text-tt-muted italic py-4 text-center w-full"
                        )
                    else:
                        columns = [
                            {
                                "name": "target",
                                "label": "Observation",
                                "field": "target_display",
                                "align": "left",
                            },
                            {
                                "name": "guessed",
                                "label": "Your guess",
                                "field": "guessed_display",
                                "align": "left",
                            },
                            {
                                "name": "count",
                                "label": "Times",
                                "field": "count",
                                "align": "center",
                            },
                        ]
                        rows = [
                            {
                                "taxon_keys": [str(c.target_taxon_key), str(c.guessed_taxon_key)],
                                "pair_key": json.dumps([str(c.target_taxon_key), str(c.guessed_taxon_key)]),
                                "target_display": c.target_display,
                                "target_canonical": c.target_canonical,
                                "guessed_display": c.guessed_display,
                                "guessed_canonical": c.guessed_canonical,
                                "count": c.count,
                            }
                            for c in confusion
                        ]
                        pair_table = ui.table(
                            columns=columns, rows=rows, row_key="pair_key"
                        ).classes("w-full bg-tt-surface text-tt-main rounded-md").props(
                            "flat bordered dense"
                        )

                        add_practice_action(pair_table)

                        for column, field, scientific in [("target", "target_display", "target_canonical"), ("guessed", "guessed_display", "guessed_canonical")]:
                            pair_table.add_slot("body-cell-" + column, f"""
                                <q-td :props="props">
                                  <div>{{{{ props.row.{field} }}}}</div>
                                  <div v-if="props.row.{field} !== props.row.{scientific}" class="text-tt-muted text-xs">{{{{ props.row.{scientific} }}}}</div>
                                </q-td>
                            """)

        # Reuse the same controls and refresh data when returning from practice.
        refresh_dashboard()
    return refresh_dashboard
