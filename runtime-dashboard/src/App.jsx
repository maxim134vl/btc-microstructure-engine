import { useEffect, useState } from "react";
import axios from "axios";

export default function App() {

    const [runtime, setRuntime] = useState([]);

    async function loadRuntime() {

        try {

            const response = await axios.get(
                "http://localhost:8000/runtime"
            );

            setRuntime(
                response.data
            );

        } catch (err) {

            console.error(err);

        }

    }

    useEffect(() => {

        loadRuntime();

        const interval = setInterval(
            loadRuntime,
            2000
        );

        return () => clearInterval(interval);

    }, []);

    return (

        <div style={{

            background: "#0f172a",
            minHeight: "100vh",
            color: "white",
            padding: "30px",
            fontFamily: "Arial"

        }}>

            <h1 style={{

                fontSize: "32px",
                marginBottom: "30px"

            }}>

                Runtime Monitor

            </h1>

            <table style={{

                width: "100%",
                borderCollapse: "collapse"

            }}>

                <thead>

                    <tr style={{

                        background: "#1e293b"

                    }}>

                        <th style={cell}>
                            Engine
                        </th>

                        <th style={cell}>
                            Status
                        </th>

                        <th style={cell}>
                            Duration
                        </th>

                        <th style={cell}>
                            Timestamp
                        </th>

                    </tr>

                </thead>

                <tbody>

                    {runtime.map((row, index) => (

                        <tr
                            key={index}
                            style={{
                                borderBottom:
                                    "1px solid #334155"
                            }}
                        >

                            <td style={cell}>
                                {row.engine}
                            </td>

                            <td style={{

                                ...cell,

                                color:

                                    row.status ===
                                    "SUCCESS"

                                    ? "#4ade80"

                                    : row.status ===
                                    "FAILED"

                                    ? "#f87171"

                                    : "#facc15"

                            }}>

                                {row.status}

                            </td>

                            <td style={cell}>
                                {row.duration}
                            </td>

                            <td style={cell}>
                                {row.timestamp}
                            </td>

                        </tr>

                    ))}

                </tbody>

            </table>

        </div>

    );

}

const cell = {

    padding: "12px",
    textAlign: "left"

};