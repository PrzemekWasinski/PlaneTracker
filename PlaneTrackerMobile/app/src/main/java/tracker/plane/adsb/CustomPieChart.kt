package tracker.plane.adsb

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import android.widget.ScrollView
import kotlin.math.min

class CustomPieChart @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 32f
        textAlign = Paint.Align.CENTER
    }

    private val legendPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 28f
    }

    private val rect = RectF()
    private var data: List<PieSlice> = emptyList()
    private var legendScrollY = 0f
    private var maxLegendScrollY = 0f
    private var isScrollingLegend = false
    private var lastTouchY = 0f

    private val colors = listOf(
        Color.parseColor("#FF6B6B"),
        Color.parseColor("#4ECDC4"),
        Color.parseColor("#45B7D1"),
        Color.parseColor("#96CEB4"),
        Color.parseColor("#FFEAA7"),
        Color.parseColor("#DDA0DD"),
        Color.parseColor("#98D8C8"),
        Color.parseColor("#F7DC6F"),
        Color.parseColor("#BB8FCE"),
        Color.parseColor("#85C1E6")
    )

    data class PieSlice(val label: String, val value: Float, val color: Int, val count: Int)

    fun setData(manufacturers: Map<String, Int>) {
        val total = manufacturers.values.sum().toFloat()

        // Sort by count (highest to lowest) and create pie slices
        data = manufacturers.entries
            .sortedByDescending { it.value }
            .mapIndexed { index, entry ->
                PieSlice(
                    label = entry.key,
                    value = (entry.value / total) * 360f,
                    color = colors[index % colors.size],
                    count = entry.value
                )
            }

        // Calculate max scroll for legend
        calculateMaxLegendScroll()
        legendScrollY = 0f // Reset scroll position
        invalidate()
    }

    private fun calculateMaxLegendScroll() {
        val legendItemHeight = 40f
        val legendHeight = data.size * legendItemHeight
        val availableHeight = height * 0.4f // Available space for legend
        maxLegendScrollY = maxOf(0f, legendHeight - availableHeight)
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        calculateMaxLegendScroll()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val centerY = height * 0.4f
        val radius = min(width / 2f, centerY) * 0.8f
        val legendStartY = centerY + radius + 50f

        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                lastTouchY = event.y
                isScrollingLegend = event.y > legendStartY

                // If touching in legend area and there's content to scroll, request parent not to intercept
                if (isScrollingLegend && maxLegendScrollY > 0) {
                    parent.requestDisallowInterceptTouchEvent(true)
                }
                return true
            }

            MotionEvent.ACTION_MOVE -> {
                if (isScrollingLegend && maxLegendScrollY > 0) {
                    val deltaY = lastTouchY - event.y
                    val newScrollY = (legendScrollY + deltaY).coerceIn(0f, maxLegendScrollY)

                    // Only consume the event if we actually scrolled
                    if (newScrollY != legendScrollY) {
                        legendScrollY = newScrollY
                        lastTouchY = event.y
                        invalidate()
                        return true
                    }
                }
            }

            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                isScrollingLegend = false
                parent.requestDisallowInterceptTouchEvent(false)
            }
        }

        return super.onTouchEvent(event)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        if (data.isEmpty()) {
            // Draw "No Data" message
            textPaint.textSize = 48f
            canvas.drawText(
                "No Data Available",
                width / 2f,
                height / 2f,
                textPaint
            )
            return
        }

        val centerX = width / 2f
        val centerY = height * 0.4f // Move chart up to make room for legend
        val radius = min(centerX, centerY) * 0.8f

        rect.set(
            centerX - radius,
            centerY - radius,
            centerX + radius,
            centerY + radius
        )

        var startAngle = 0f

        // Draw pie slices
        data.forEach { slice ->
            paint.color = slice.color
            canvas.drawArc(rect, startAngle, slice.value, true, paint)
            startAngle += slice.value
        }

        // Draw center circle (donut effect)
        paint.color = Color.BLACK
        canvas.drawCircle(centerX, centerY, radius * 0.5f, paint)

        // Draw center text
        textPaint.textSize = 36f
        textPaint.color = Color.WHITE
        canvas.drawText(
            "Aircraft",
            centerX,
            centerY - 10f,
            textPaint
        )
        canvas.drawText(
            "Stats",
            centerX,
            centerY + 25f,
            textPaint
        )

        // Draw scrollable legend
        drawScrollableLegend(canvas, centerY + radius + 50f)
    }

    private fun drawScrollableLegend(canvas: Canvas, startY: Float) {
        val legendItemHeight = 40f
        val colorBoxSize = 24f
        val margin = 16f
        val legendAreaHeight = height - startY

        // Create clipping rectangle for legend area
        canvas.save()
        canvas.clipRect(0f, startY, width.toFloat(), height.toFloat())

        var currentY = startY - legendScrollY
        val total = data.sumOf { it.count }

        data.forEach { slice ->
            // Only draw items that are visible in the clipped area
            if (currentY + legendItemHeight >= startY && currentY <= height) {
                val percentage = ((slice.count.toFloat() / total) * 100f).toDouble()
                val rounded = String.format("%.2f", percentage) // "3.14"

                // Draw color box with rounded corners
                paint.color = slice.color
                val colorRect = RectF(
                    margin,
                    currentY,
                    margin + colorBoxSize,
                    currentY + colorBoxSize
                )
                canvas.drawRoundRect(colorRect, 4f, 4f, paint)

                // Draw label, count and percentage
                legendPaint.color = Color.WHITE

                val labelText = "${slice.label}: ${slice.count} ($rounded%)"
                canvas.drawText(
                    labelText,
                    margin + colorBoxSize + 16f,
                    currentY + colorBoxSize / 2f + legendPaint.textSize / 3f,
                    legendPaint
                )
            }

            currentY += legendItemHeight
        }

        canvas.restore()

        // Draw scroll indicator if content is scrollable
        if (maxLegendScrollY > 0) {
            drawScrollIndicator(canvas, startY, legendAreaHeight)
        }
    }

    private fun drawScrollIndicator(canvas: Canvas, startY: Float, legendAreaHeight: Float) {
        val indicatorWidth = 4f
        val indicatorX = width - 12f
        val indicatorHeight = (legendAreaHeight / (maxLegendScrollY + legendAreaHeight)) * legendAreaHeight
        val indicatorY = startY + (legendScrollY / maxLegendScrollY) * (legendAreaHeight - indicatorHeight)

        // Draw scroll track
        paint.color = Color.parseColor("#33FFFFFF")
        canvas.drawRect(
            indicatorX,
            startY,
            indicatorX + indicatorWidth,
            startY + legendAreaHeight,
            paint
        )

        // Draw scroll thumb
        paint.color = Color.parseColor("#80FFFFFF")
        val thumbRect = RectF(
            indicatorX,
            indicatorY,
            indicatorX + indicatorWidth,
            indicatorY + indicatorHeight
        )
        canvas.drawRoundRect(thumbRect, 2f, 2f, paint)
    }
}