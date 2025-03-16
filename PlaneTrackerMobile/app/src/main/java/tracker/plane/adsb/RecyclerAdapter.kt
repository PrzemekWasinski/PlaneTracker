package tracker.plane.adsb

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import org.w3c.dom.Text

class RecyclerAdapter : RecyclerView.Adapter<RecyclerAdapter.ViewHolder>() {

    private var planeList = mutableListOf<PlaneData>()

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.plane_list, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val plane = planeList[position]
        holder.planeModel.text = plane.planeModel
        holder.airlineName.text = plane.airlineName
        holder.registration.text = plane.registration
        holder.spottedAt.text = plane.spottedAt
    }

    override fun getItemCount(): Int {
        return planeList.size
    }

    fun updateData(newList: List<PlaneData>) {
        planeList.clear()
        planeList.addAll(newList)
        notifyDataSetChanged()
    }

    inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        var planeModel: TextView = itemView.findViewById(R.id.planeModel)
        var airlineName: TextView = itemView.findViewById(R.id.airlineName)
        var registration: TextView = itemView.findViewById(R.id.registration)
        var spottedAt: TextView = itemView.findViewById(R.id.spottedAt)
    }
}
