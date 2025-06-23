package tracker.plane.adsb

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

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

    data class PieSlice(val label: String, val value: Float, val color: Int)

    fun setData(manufacturers: Map<String, Int>) {
        val total = manufacturers.values.sum().toFloat()
        data = manufacturers.entries.mapIndexed { index, entry ->
            PieSlice(
                label = entry.key,
                value = (entry.value / total) * 360f,
                color = colors[index % colors.size]
            )
        }
        invalidate()
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

        // Draw legend
        drawLegend(canvas, centerY + radius + 50f)
    }

    private fun drawLegend(canvas: Canvas, startY: Float) {
        val total = data.sumOf { it.value.toDouble() / 360.0 * 100 }.toFloat()
        var currentY = startY
        val legendItemHeight = 40f
        val colorBoxSize = 24f
        val margin = 16f

        data.forEach { slice ->
            val percentage = (slice.value / 360f * 100f).toInt()

            // Draw color box
            paint.color = slice.color
            canvas.drawRect(
                margin,
                currentY,
                margin + colorBoxSize,
                currentY + colorBoxSize,
                paint
            )

            // Draw label and percentage
            legendPaint.color = Color.WHITE
            canvas.drawText(
                "${slice.label}: $percentage%",
                margin + colorBoxSize + 16f,
                currentY + colorBoxSize / 2f + legendPaint.textSize / 3f,
                legendPaint
            )

            currentY += legendItemHeight
        }
    }
}