package com.example.planetracker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.icu.text.SimpleDateFormat
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import android.os.AsyncTask
import java.util.Date

class NotificationReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        FetchPlanesTask(context).execute()
        val updateIntent = Intent("com.example.planetracker.UPDATE_VIEW")
        val sdf = SimpleDateFormat("HH:mm:ss")
        val currentTime = sdf.format(Date())

        updateIntent.putExtra("update_text", "Last Updated: ${currentTime}")
        updateIntent.flags = Intent.FLAG_RECEIVER_FOREGROUND
        context?.sendBroadcast(updateIntent)
    }

    private class FetchPlanesTask(val context: Context) : AsyncTask<Void, Void, String>() {
        override fun doInBackground(vararg params: Void?): String {
            return getPlanes()
        }

        override fun onPostExecute(result: String?) {
            super.onPostExecute(result)
            if (result != null) {
                showNotification(context, result)
            }
        }

        var notificationMessage = "Plane Tracker"

        private fun getPlanes(): String {
            val sdf = SimpleDateFormat("HH")
            val currentTime = sdf.format(Date()).toInt()

            if (currentTime > 7 && currentTime < 18) {
                notificationMessage = "Planes Nearby"
                val client = OkHttpClient()

                val request = Request.Builder()
                    .url("https://flight-radar1.p.rapidapi.com/flights/list-in-boundary?bl_lat=51.636985&bl_lng=-0.034332&tr_lat=51.725474&tr_lng=0.211487&limit=300")
                    .get()
                    .addHeader("x-rapidapi-key", "Rapid Api Key")
                    .addHeader("x-rapidapi-host", "flight-radar1.p.rapidapi.com")
                    .build()

                try {
                    val response = client.newCall(request).execute()

                    val responseString = response.peekBody(Long.MAX_VALUE).string()
                    if (responseString.isEmpty()) {
                        return "API Error: Response is empty"
                    }

                    val jsonObject = JSONObject(responseString)
                    if (!jsonObject.has("aircraft")) {
                        if (jsonObject.has("message")) {
                            return jsonObject.getString("message")
                        }
                        return "API Error: 'aircraft' key not found"
                    }

                    val planeArray = jsonObject.getJSONArray("aircraft")
                    val planeList = mutableListOf<String>()

                    for (i in 0 until planeArray.length()) {
                        val planeInfo = planeArray.getJSONArray(i).optString(9, "Unknown")
                        planeList.add(planeInfo)
                    }

                    if (planeList.size < 2) {
                        return "No planes found"
                    }
                    notificationMessage = "Planes Nearby"
                    return planeList.joinToString(", ")
                } catch (e: Exception) {
                    return "Error: ${e.localizedMessage ?: "Unknown error"}"
                }
            } else {
                return "It's too dark"
            }
        }

        private fun showNotification(context: Context, planeString: String) {
            val channelId = "hallo_notification_channel"
            val channelName = "Hallo Notifications"
            val notificationManager =
                context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                val channel = NotificationChannel(channelId, channelName, NotificationManager.IMPORTANCE_DEFAULT)
                notificationManager.createNotificationChannel(channel)
            }

            val notification = NotificationCompat.Builder(context, channelId)
                .setContentTitle(notificationMessage)
                .setContentText(planeString)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setAutoCancel(true)
                .build()

            notificationManager.notify(1, notification)
        }
    }
}